// Command edgespace-central is the main entry point for the Orange Pi orchestrator.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"edgespace/central/internal/httpws"
	"edgespace/central/internal/store"
)

const shutdownTimeout = 5 * time.Second

type mockClusterFlag string

func (m *mockClusterFlag) String() string { return string(*m) }
func (m *mockClusterFlag) IsBoolFlag() bool {
	return true
}
func (m *mockClusterFlag) Set(s string) error {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "", "true", "1", "inproc":
		*m = "inproc"
	case "false", "0":
		*m = "false"
	case "udp":
		*m = "udp"
	default:
		return fmt.Errorf("invalid --mock-cluster %q: must be false|inproc|udp", s)
	}
	return nil
}

type leva2Flag struct {
	name  string
	value string
}

type config struct {
	db            string
	migrations    string
	udpAddr       string
	broadcastAddr string
	ipcAddr       string
	httpAddr      string
	wsHz          int
	mockCluster   mockClusterFlag
	mockAI        bool
	scenario      string
	seed          int64
	timeScale     float64
	logLevel      string
	leva2Used     []leva2Flag
}

func main() {
	sigCtx, stopSig := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stopSig()
	os.Exit(run(sigCtx, os.Args[1:], os.Stdout))
}

func run(ctx context.Context, args []string, stdout io.Writer) int {
	if stdout == nil {
		stdout = os.Stdout
	}
	errOut := io.Writer(os.Stderr)
	if stdout != os.Stdout {
		errOut = stdout
	}
	cfg, err := parseFlags(args, errOut)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return 2
	}

	log := newLogger(cfg.logLevel, stdout)
	slog.SetDefault(log)

	for _, f := range cfg.leva2Used {
		log.Warn("not implemented in Leva 1", "flag", f.name, "value", f.value)
	}

	// 1. Start order (§2.8): store(migrate) -> ... -> httpws
	st, err := store.New(store.Config{
		DBPath:        cfg.db,
		MigrationsDir: cfg.migrations,
	}, store.Deps{Logger: log})
	if err != nil {
		log.Error("store init failed", "err", err)
		return 1
	}

	srv, err := httpws.New(httpws.Config{
		Addr: cfg.httpAddr,
		WSHz: cfg.wsHz,
	}, httpws.Deps{
		Logger: log,
		Reader: st.Reader(),
		StoreStats: func() httpws.StoreStats {
			stats := st.Stats()
			return httpws.StoreStats{Commits: stats.Commits, Backlog: stats.Backlog}
		},
	})
	if err != nil {
		log.Error("httpws init failed", "err", err)
		return 1
	}

	storeCtx, cancelStore := context.WithCancel(context.Background())
	defer cancelStore()
	httpCtx, cancelHTTP := context.WithCancel(context.Background())
	defer cancelHTTP()

	storeDone := make(chan error, 1)
	httpDone := make(chan error, 1)

	go func() { storeDone <- st.Run(storeCtx) }()
	go func() { httpDone <- srv.Run(httpCtx) }()

	var exitCode int
	select {
	case <-ctx.Done():
		log.Info("shutdown signal received")
	case err := <-httpDone:
		if err != nil && !errors.Is(err, context.Canceled) {
			log.Error("httpws exited unexpectedly", "err", err)
			exitCode = 1
		}
		httpDone = nil
	case err := <-storeDone:
		if err != nil && !errors.Is(err, context.Canceled) {
			log.Error("store exited unexpectedly", "err", err)
			exitCode = 1
		}
		storeDone = nil
	}

	// 2. Strict shutdown order (§2.8, 5s total budget):
	// httpws (stop accept, close WS 1001) -> ... -> store (drain + flush + checkpoint TRUNCATE)
	shutCtx, cancelShut := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancelShut()

	cancelHTTP()
	if httpDone != nil {
		select {
		case err := <-httpDone:
			if err != nil && !errors.Is(err, context.Canceled) {
				log.Error("httpws shutdown error", "err", err)
				exitCode = 1
			}
		case <-shutCtx.Done():
			log.Warn("httpws shutdown timeout")
			exitCode = 1
		}
	}

	cancelStore()
	if storeDone != nil {
		select {
		case err := <-storeDone:
			if err != nil && !errors.Is(err, context.Canceled) {
				log.Error("store shutdown error", "err", err)
				exitCode = 1
			}
		case <-shutCtx.Done():
			log.Warn("store shutdown timeout")
			exitCode = 1
		}
	}

	log.Info("central stopped")
	return exitCode
}

func parseFlags(args []string, errOut io.Writer) (config, error) {
	fs := flag.NewFlagSet("edgespace-central", flag.ContinueOnError)
	if errOut != nil {
		fs.SetOutput(errOut)
	}
	cfg := config{
		db:            "./var/edgespace.db",
		migrations:    "../database/migrations",
		udpAddr:       ":5005",
		broadcastAddr: "10.42.0.255:5005",
		ipcAddr:       "127.0.0.1:5006",
		httpAddr:      ":8000",
		wsHz:          2,
		mockCluster:   "false",
		mockAI:        false,
		scenario:      "",
		seed:          1,
		timeScale:     1,
		logLevel:      "info",
	}

	fs.StringVar(&cfg.db, "db", cfg.db, "SQLite WAL database path")
	fs.StringVar(&cfg.migrations, "migrations", cfg.migrations, "SQL migrations directory")
	fs.StringVar(&cfg.udpAddr, "udp-addr", cfg.udpAddr, "UDP rx address (Leva 2)")
	fs.StringVar(&cfg.broadcastAddr, "broadcast-addr", cfg.broadcastAddr, "UDP CLUSTER_SYNC broadcast address (Leva 2)")
	fs.StringVar(&cfg.ipcAddr, "ipc-addr", cfg.ipcAddr, "Edge AI IPC address (Leva 2)")
	fs.StringVar(&cfg.httpAddr, "http-addr", cfg.httpAddr, "HTTP/WS listen address")
	fs.IntVar(&cfg.wsHz, "ws-hz", cfg.wsHz, "TELEMETRY_FRAME broadcast rate in Hz (2-10)")
	fs.Var(&cfg.mockCluster, "mock-cluster", "Mock cluster mode: false|inproc|udp (Leva 2)")
	fs.BoolVar(&cfg.mockAI, "mock-ai", cfg.mockAI, "In-process mock Edge AI worker (Leva 2)")
	fs.StringVar(&cfg.scenario, "scenario", cfg.scenario, "Simulation scenario (Leva 2)")
	fs.Int64Var(&cfg.seed, "seed", cfg.seed, "Deterministic sim seed (Leva 2)")
	fs.Float64Var(&cfg.timeScale, "time-scale", cfg.timeScale, "Simulation time scale (Leva 2)")
	fs.StringVar(&cfg.logLevel, "log-level", cfg.logLevel, "Log level: debug|info|warn|error")

	if err := fs.Parse(args); err != nil {
		return config{}, err
	}

	if cfg.wsHz < 2 || cfg.wsHz > 10 {
		return config{}, fmt.Errorf("invalid --ws-hz %d: must be in range 2..10", cfg.wsHz)
	}
	if _, ok := parseLogLevel(cfg.logLevel); !ok {
		return config{}, fmt.Errorf("invalid --log-level %q: must be debug|info|warn|error", cfg.logLevel)
	}

	fs.Visit(func(f *flag.Flag) {
		switch f.Name {
		case "udp-addr", "broadcast-addr", "ipc-addr", "scenario", "seed", "time-scale":
			cfg.leva2Used = append(cfg.leva2Used, leva2Flag{name: f.Name, value: f.Value.String()})
		case "mock-cluster":
			if cfg.mockCluster != "false" {
				cfg.leva2Used = append(cfg.leva2Used, leva2Flag{name: f.Name, value: f.Value.String()})
			}
		case "mock-ai":
			if cfg.mockAI {
				cfg.leva2Used = append(cfg.leva2Used, leva2Flag{name: f.Name, value: f.Value.String()})
			}
		}
	})

	return cfg, nil
}

func parseLogLevel(levelStr string) (slog.Level, bool) {
	switch strings.ToLower(strings.TrimSpace(levelStr)) {
	case "debug":
		return slog.LevelDebug, true
	case "info":
		return slog.LevelInfo, true
	case "warn", "warning":
		return slog.LevelWarn, true
	case "error":
		return slog.LevelError, true
	default:
		return slog.LevelInfo, false
	}
}

func newLogger(levelStr string, out io.Writer) *slog.Logger {
	if out == nil {
		out = os.Stdout
	}
	lvl, _ := parseLogLevel(levelStr)
	return slog.New(slog.NewJSONHandler(out, &slog.HandlerOptions{Level: lvl}))
}
