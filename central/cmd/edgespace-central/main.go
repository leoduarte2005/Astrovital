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
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"edgespace/central/internal/cluster"
	"edgespace/central/internal/contracts"
	"edgespace/central/internal/httpws"
	"edgespace/central/internal/ipc"
	"edgespace/central/internal/pipeline"
	"edgespace/central/internal/session"
	"edgespace/central/internal/sim"
	"edgespace/central/internal/store"
	"edgespace/central/internal/udp"
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

type config struct {
	db               string
	migrations       string
	udpAddr          string
	broadcastAddr    string
	ipcAddr          string
	httpAddr         string
	wsHz             int
	mockCluster      mockClusterFlag
	mockAI           bool
	scenario         string
	seed             int64
	timeScale        float64
	simLoss          float64
	simJitterMs      int
	mockAILatencyMs  int
	mockAIDropAck    bool
	mockAICrashAfter time.Duration
	logLevel         string
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

	// 1. Start order (§2.8): store -> session -> mockAI -> ipc -> pipeline -> cluster -> udp/sim -> httpws.
	st, err := store.New(store.Config{
		DBPath:        cfg.db,
		MigrationsDir: cfg.migrations,
	}, store.Deps{Logger: log})
	if err != nil {
		log.Error("store init failed", "err", err)
		return 1
	}

	storeCtx, cancelStore := context.WithCancel(context.Background())
	defer cancelStore()
	storeDone := make(chan error, 1)
	go func() { storeDone <- st.Run(storeCtx) }()

	var mockAI *sim.MockAI
	var mockAICtx context.Context
	var cancelMockAI context.CancelFunc
	var mockAIDone chan error
	effectiveIPCAddr := cfg.ipcAddr
	if cfg.mockAI {
		mockAI, err = sim.NewMockAI(sim.MockAIConfig{
			Addr:       cfg.ipcAddr,
			Logger:     log,
			Scenario:   cfg.scenario,
			LatencyMs:  cfg.mockAILatencyMs,
			DropAck:    cfg.mockAIDropAck,
			CrashAfter: cfg.mockAICrashAfter,
		})
		if err != nil {
			log.Error("mock-ai init failed", "err", err)
			cancelStore()
			<-storeDone
			return 1
		}
		effectiveIPCAddr = mockAI.Addr()
		mockAICtx, cancelMockAI = context.WithCancel(context.Background())
		defer func() {
			if cancelMockAI != nil {
				cancelMockAI()
			}
		}()
		mockAIDone = make(chan error, 1)
		go func() { mockAIDone <- mockAI.Run(mockAICtx) }()
	}

	var sessMgr *session.Manager
	ipcClient, err := ipc.New(ipc.Config{Addr: effectiveIPCAddr}, ipc.Deps{
		Logger: log,
		OnReconnect: func() {
			if sessMgr != nil {
				sessMgr.NotifyIPCReconnect()
			}
		},
	})
	if err != nil {
		log.Error("ipc init failed", "err", err)
		return 1
	}

	pipeDataCh := make(chan pipeline.DataMsg, udp.DataChCap)
	pipeInfCh := make(chan contracts.AIInferencePayload, 16)
	pipeSelfExamCh := make(chan pipeline.SelfExamInput, 16)
	pipeEventCh := make(chan contracts.AlertEventPayload, 64)

	clusterMgr := cluster.New(cluster.Config{ScanInterval: 50 * time.Millisecond, AILink: "offline"}, st)
	if err := clusterMgr.Load(context.Background()); err != nil {
		log.Warn("cluster registry load failed", "err", err)
	}

	latestClusterStatus := &atomic.Pointer[contracts.ClusterStatusPayload]{}
	lastInference := &atomic.Pointer[contracts.AIInferencePayload]{}

	var udpSink *udp.ChannelSink
	var udpRx *udp.Receiver
	var udpTx *udp.Transmitter
	if cfg.mockCluster != "inproc" {
		udpSink = udp.NewChannelSink()
		udpRx = udp.NewReceiver(udp.ReceiverConfig{Addr: cfg.udpAddr}, udpSink)
		udpTx = udp.NewTransmitter(udp.TransmitterConfig{
			BroadcastAddr: cfg.broadcastAddr,
			InitialMode:   contracts.ModeCabinTomography,
		}, clusterSlotPlanAdapter{cm: clusterMgr})
	} else {
		udpRx = udp.NewReceiver(udp.ReceiverConfig{RxDisabled: true}, udp.NewChannelSink())
	}

	wsOutCh := make(chan contracts.WSEnvelope, 128)
	sessMgr = session.New(session.Config{InitialMode: contracts.ModeCabinTomography}, session.Deps{
		Store:            storeSessionAdapter{st: st},
		IPC:              ipcSessionAdapter{client: ipcClient},
		UDP:              udpSessionAdapter{tx: udpTx, inproc: cfg.mockCluster == "inproc", log: log},
		UI:               uiSessionAdapter{eventCh: wsOutCh},
		SelfExamNotifier: selfExamNotifierAdapter{ch: pipeSelfExamCh},
	})

	sessCtx, cancelSession := context.WithCancel(context.Background())
	defer cancelSession()
	sessDone := make(chan error, 1)
	go func() { sessDone <- sessMgr.Run(sessCtx) }()

	ipcCtx, cancelIPC := context.WithCancel(context.Background())
	defer cancelIPC()
	ipcDone := make(chan error, 1)
	go func() { ipcDone <- ipcClient.Run(ipcCtx) }()

	if cfg.mockAI {
		connDeadline := time.Now().Add(500 * time.Millisecond)
		for !ipcClient.Connected() && time.Now().Before(connDeadline) {
			time.Sleep(5 * time.Millisecond)
		}
	}

	initCrewCtx, cancelInitCrew := context.WithTimeout(context.Background(), 2*time.Second)
	if _, err := sessMgr.SetCrew(initCrewCtx, "crew_001"); err != nil {
		log.Warn("initial SetCrew(crew_001) failed", "err", err)
	}
	cancelInitCrew()

	pipe := pipeline.New(pipeline.Config{}, pipeline.Deps{
		DataCh:      pipeDataCh,
		InferenceCh: pipeInfCh,
		SelfExamCh:  pipeSelfExamCh,
		Session:     pipelineSessionAdapter{sess: sessMgr},
		LinkMask:    pipelineMaskAdapter{cm: clusterMgr},
		IPC:         pipelineIPCAdapter{client: ipcClient},
		Store:       pipelineStoreAdapter{st: st},
		EventCh:     pipeEventCh,
	})

	var devCtrl httpws.DevController
	var mockCluster *sim.MockCluster
	if cfg.mockCluster != "false" {
		mockCluster, err = buildMockCluster(ctx, cfg, log, clusterMgr, sessMgr, pipeDataCh, udpRx, mockAI)
		if err != nil {
			log.Error("mock-cluster init failed", "err", err)
			return 1
		}
	}
	if mockCluster != nil || mockAI != nil {
		devCtrl = devControllerAdapter{mc: mockCluster, ai: mockAI}
	}

	srv, err := buildHTTPServer(cfg, log, st, sessMgr, pipe, clusterMgr, ipcClient, udpSink, devCtrl, lastInference, latestClusterStatus)
	if err != nil {
		log.Error("httpws init failed", "err", err)
		return 1
	}
	pipe.Latest = srv.Latest()

	pipeCtx, cancelPipe := context.WithCancel(context.Background())
	defer cancelPipe()
	pipeDone := make(chan error, 1)
	go func() { pipeDone <- pipe.Run(pipeCtx) }()

	clusterCtx, cancelCluster := context.WithCancel(context.Background())
	defer cancelCluster()
	clusterDone := make(chan error, 1)
	go func() { clusterDone <- clusterMgr.Run(clusterCtx) }()

	simUDPCtx, cancelSimUDP := context.WithCancel(context.Background())
	defer cancelSimUDP()
	var simDone, udpRxDone, udpTxDone chan error
	if cfg.mockCluster != "inproc" {
		udpRxDone = make(chan error, 1)
		go func() { udpRxDone <- udpRx.Run(simUDPCtx) }()
		udpTxDone = make(chan error, 1)
		go func() { udpTxDone <- udpTx.Run(simUDPCtx) }()
	}
	if mockCluster != nil {
		simDone = make(chan error, 1)
		go func() { simDone <- mockCluster.Run(simUDPCtx) }()
	}

	bridgeCtx, cancelBridges := context.WithCancel(context.Background())
	defer cancelBridges()
	var bridgeWG sync.WaitGroup
	startBridges(bridgeCtx, &bridgeWG, log, srv.EventCh(), wsOutCh, pipeInfCh, pipeEventCh, pipeDataCh,
		udpSink, clusterMgr, ipcClient, sessMgr, lastInference, latestClusterStatus)

	httpCtx, cancelHTTP := context.WithCancel(context.Background())
	defer cancelHTTP()
	httpDone := make(chan error, 1)
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

	// 2. Strict reverse shutdown order (§2.8, 5s total budget):
	// httpws -> sim/udp -> cluster -> pipeline -> ipc/mockAI -> bridges -> session -> store.
	shutCtx, cancelShut := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancelShut()

	cancelHTTP()
	waitStep(shutCtx, log, "httpws", httpDone, &exitCode)
	cancelSimUDP()
	waitStep(shutCtx, log, "sim", simDone, &exitCode)
	waitStep(shutCtx, log, "udp_rx", udpRxDone, &exitCode)
	waitStep(shutCtx, log, "udp_tx", udpTxDone, &exitCode)
	cancelCluster()
	waitStep(shutCtx, log, "cluster", clusterDone, &exitCode)
	cancelPipe()
	waitStep(shutCtx, log, "pipeline", pipeDone, &exitCode)
	cancelIPC()
	waitStep(shutCtx, log, "ipc", ipcDone, &exitCode)
	if cancelMockAI != nil {
		cancelMockAI()
		waitStep(shutCtx, log, "mock_ai", mockAIDone, &exitCode)
	}
	cancelBridges()
	bridgeDone := make(chan struct{})
	go func() { bridgeWG.Wait(); close(bridgeDone) }()
	select {
	case <-bridgeDone:
	case <-shutCtx.Done():
		log.Warn("bridges shutdown timeout")
		exitCode = 1
	}
	cancelSession()
	waitStep(shutCtx, log, "session", sessDone, &exitCode)
	cancelStore()
	waitStep(shutCtx, log, "store", storeDone, &exitCode)

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
	fs.StringVar(&cfg.udpAddr, "udp-addr", cfg.udpAddr, "UDP rx address")
	fs.StringVar(&cfg.broadcastAddr, "broadcast-addr", cfg.broadcastAddr, "UDP CLUSTER_SYNC broadcast address")
	fs.StringVar(&cfg.ipcAddr, "ipc-addr", cfg.ipcAddr, "Edge AI IPC address")
	fs.StringVar(&cfg.httpAddr, "http-addr", cfg.httpAddr, "HTTP/WS listen address")
	fs.IntVar(&cfg.wsHz, "ws-hz", cfg.wsHz, "TELEMETRY_FRAME broadcast rate in Hz (2-10)")
	fs.Var(&cfg.mockCluster, "mock-cluster", "Mock cluster mode: false|inproc|udp")
	fs.BoolVar(&cfg.mockAI, "mock-ai", cfg.mockAI, "In-process mock Edge AI worker")
	fs.StringVar(&cfg.scenario, "scenario", cfg.scenario, "Simulation scenario: hypercapnia|sans|solar_storm|dehydration_sleep|node_loss")
	fs.Int64Var(&cfg.seed, "seed", cfg.seed, "Deterministic sim seed")
	fs.Float64Var(&cfg.timeScale, "time-scale", cfg.timeScale, "Simulation time scale")
	fs.Float64Var(&cfg.simLoss, "sim-loss", cfg.simLoss, "Simulated packet drop probability (0.0..1.0)")
	fs.IntVar(&cfg.simJitterMs, "sim-jitter-ms", cfg.simJitterMs, "Simulated max TX jitter (ms)")
	fs.IntVar(&cfg.mockAILatencyMs, "mock-ai-latency-ms", cfg.mockAILatencyMs, "Extra MockAI response latency (ms)")
	fs.BoolVar(&cfg.mockAIDropAck, "mock-ai-drop-ack", cfg.mockAIDropAck, "Drop SET_ACTIVE_CREW ACKs in MockAI")
	fs.DurationVar(&cfg.mockAICrashAfter, "mock-ai-crash-after", cfg.mockAICrashAfter, "Close MockAI connections after duration")
	fs.StringVar(&cfg.logLevel, "log-level", cfg.logLevel, "Log level: debug|info|warn|error")

	if err := fs.Parse(normalizeArgs(args)); err != nil {
		return config{}, err
	}
	if fs.NArg() > 0 {
		return config{}, fmt.Errorf("unexpected positional arguments: %v", fs.Args())
	}
	if cfg.wsHz < 2 || cfg.wsHz > 10 {
		return config{}, fmt.Errorf("invalid --ws-hz %d: must be in range 2..10", cfg.wsHz)
	}
	if cfg.timeScale <= 0 {
		return config{}, fmt.Errorf("invalid --time-scale %v: must be > 0", cfg.timeScale)
	}
	if cfg.simLoss < 0 || cfg.simLoss > 1 {
		return config{}, fmt.Errorf("invalid --sim-loss %v: must be in [0,1]", cfg.simLoss)
	}
	if cfg.simJitterMs < 0 || cfg.mockAILatencyMs < 0 || cfg.mockAICrashAfter < 0 {
		return config{}, errors.New("chaos latency/jitter/crash-after flags must be >= 0")
	}
	if !sim.IsValidScenario(cfg.scenario) {
		return config{}, fmt.Errorf("invalid --scenario %q", cfg.scenario)
	}
	if _, ok := parseLogLevel(cfg.logLevel); !ok {
		return config{}, fmt.Errorf("invalid --log-level %q: must be debug|info|warn|error", cfg.logLevel)
	}
	return cfg, nil
}

// normalizeArgs allows `--mock-cluster inproc` (space-separated) alongside `--mock-cluster=inproc`
// and bare `--mock-cluster` without breaking subsequent flags like `--mock-ai` or `--scenario`.
func normalizeArgs(args []string) []string {
	out := make([]string, 0, len(args))
	for i := 0; i < len(args); i++ {
		a := args[i]
		if (a == "--mock-cluster" || a == "-mock-cluster") && i+1 < len(args) && !strings.HasPrefix(args[i+1], "-") {
			out = append(out, "--mock-cluster="+args[i+1])
			i++
			continue
		}
		out = append(out, a)
	}
	return out
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
