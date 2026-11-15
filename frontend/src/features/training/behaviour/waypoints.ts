import type { CrewId } from '@/lib/data/mock/crewLore'
import type { WaypointZone } from './types'

/**
 * Waypoints of the training hangar (`data/models/hangar/edgespace_training_hangar.glb`, nodes `WP_*` and their extras).
 * Extracted once from the GLB (read only) so the behaviour can be planned without loading the model. Positions are a
 * snapshot in metres (Y up): the renderer must still place avatars from the GLB itself; if the GLB changes, regenerate.
 * Quarters (level 1, the mezzanine at y 4.2) are reached by the east stair.
 */
export interface Waypoint {
  id: string
  zone: WaypointZone
  kind: 'seat' | 'station' | 'idle' | 'entry' | 'queue'
  /** 0 = ground floor, 1 = mezzanine. */
  level: 0 | 1
  x: number
  y: number
  z: number
  facingDeg: number
  activity?: string
  role?: string
  device?: string
  /** Crew members who prefer this point (set in the GLB). */
  favoredBy?: CrewId[]
  /** Owner, for the private points of the quarters. */
  crewId?: CrewId
}

export const WAYPOINTS: readonly Waypoint[] = [
  { id: 'WP_classroom_seat_1', zone: 'classroom', kind: 'seat', level: 0, x: -54.6, y: 0, z: 23.45, facingDeg: 0 },
  { id: 'WP_classroom_seat_2', zone: 'classroom', kind: 'seat', level: 0, x: -53.4, y: 0, z: 23.45, facingDeg: 0 },
  { id: 'WP_classroom_seat_3', zone: 'classroom', kind: 'seat', level: 0, x: -49.6, y: 0, z: 23.45, facingDeg: 0 },
  { id: 'WP_classroom_seat_4', zone: 'classroom', kind: 'seat', level: 0, x: -48.4, y: 0, z: 23.45, facingDeg: 0 },
  { id: 'WP_classroom_seat_5', zone: 'classroom', kind: 'seat', level: 0, x: -54.6, y: 0, z: 25.05, facingDeg: 0 },
  { id: 'WP_classroom_seat_6', zone: 'classroom', kind: 'seat', level: 0, x: -53.4, y: 0, z: 25.05, facingDeg: 0 },
  { id: 'WP_classroom_seat_7', zone: 'classroom', kind: 'seat', level: 0, x: -49.6, y: 0, z: 25.05, facingDeg: 0 },
  { id: 'WP_classroom_seat_8', zone: 'classroom', kind: 'seat', level: 0, x: -48.4, y: 0, z: 25.05, facingDeg: 0 },
  { id: 'WP_classroom_seat_9', zone: 'classroom', kind: 'seat', level: 0, x: -54.6, y: 0, z: 26.65, facingDeg: 0 },
  { id: 'WP_classroom_seat_10', zone: 'classroom', kind: 'seat', level: 0, x: -53.4, y: 0, z: 26.65, facingDeg: 0 },
  { id: 'WP_classroom_seat_11', zone: 'classroom', kind: 'seat', level: 0, x: -49.6, y: 0, z: 26.65, facingDeg: 0 },
  { id: 'WP_classroom_seat_12', zone: 'classroom', kind: 'seat', level: 0, x: -48.4, y: 0, z: 26.65, facingDeg: 0 },
  { id: 'WP_classroom_station_1', zone: 'classroom', kind: 'station', level: 0, x: -47.5, y: 0, z: 28, facingDeg: 180, role: 'instructor' },
  { id: 'WP_classroom_entry_1', zone: 'classroom', kind: 'entry', level: 0, x: -51, y: 0, z: 21.4, facingDeg: 0 },
  { id: 'WP_medbay_seat_1', zone: 'medbay', kind: 'seat', level: 0, x: -41, y: 0, z: 27.4, facingDeg: 0, role: 'patient' },
  { id: 'WP_medbay_station_1', zone: 'medbay', kind: 'station', level: 0, x: -39.7, y: 0, z: 27.6, facingDeg: 270, role: 'medic' },
  { id: 'WP_medbay_seat_2', zone: 'medbay', kind: 'seat', level: 0, x: -35.5, y: 0, z: 27.4, facingDeg: 0, role: 'patient' },
  { id: 'WP_medbay_station_2', zone: 'medbay', kind: 'station', level: 0, x: -34.2, y: 0, z: 27.6, facingDeg: 270, role: 'medic' },
  { id: 'WP_medbay_entry_1', zone: 'medbay', kind: 'entry', level: 0, x: -37, y: 0, z: 21.4, facingDeg: 0 },
  { id: 'WP_medbay_station_3', zone: 'medbay', kind: 'station', level: 0, x: -33.4, y: 0, z: 25, facingDeg: 90, role: 'point_of_care' },
  { id: 'WP_mess_seat_1', zone: 'mess', kind: 'seat', level: 0, x: -24, y: 0, z: 23.85, facingDeg: 0 },
  { id: 'WP_mess_seat_2', zone: 'mess', kind: 'seat', level: 0, x: -24, y: 0, z: 25.35, facingDeg: 180 },
  { id: 'WP_mess_seat_3', zone: 'mess', kind: 'seat', level: 0, x: -23, y: 0, z: 23.85, facingDeg: 0 },
  { id: 'WP_mess_seat_4', zone: 'mess', kind: 'seat', level: 0, x: -23, y: 0, z: 25.35, facingDeg: 180 },
  { id: 'WP_mess_seat_5', zone: 'mess', kind: 'seat', level: 0, x: -22, y: 0, z: 23.85, facingDeg: 0 },
  { id: 'WP_mess_seat_6', zone: 'mess', kind: 'seat', level: 0, x: -22, y: 0, z: 25.35, facingDeg: 180 },
  { id: 'WP_mess_seat_7', zone: 'mess', kind: 'seat', level: 0, x: -21, y: 0, z: 23.85, facingDeg: 0 },
  { id: 'WP_mess_seat_8', zone: 'mess', kind: 'seat', level: 0, x: -21, y: 0, z: 25.35, facingDeg: 180 },
  { id: 'WP_mess_seat_9', zone: 'mess', kind: 'seat', level: 0, x: -20, y: 0, z: 23.85, facingDeg: 0 },
  { id: 'WP_mess_seat_10', zone: 'mess', kind: 'seat', level: 0, x: -20, y: 0, z: 25.35, facingDeg: 180 },
  { id: 'WP_mess_seat_11', zone: 'mess', kind: 'seat', level: 0, x: -24, y: 0, z: 26.25, facingDeg: 0 },
  { id: 'WP_mess_seat_12', zone: 'mess', kind: 'seat', level: 0, x: -24, y: 0, z: 27.75, facingDeg: 180 },
  { id: 'WP_mess_seat_13', zone: 'mess', kind: 'seat', level: 0, x: -23, y: 0, z: 26.25, facingDeg: 0 },
  { id: 'WP_mess_seat_14', zone: 'mess', kind: 'seat', level: 0, x: -23, y: 0, z: 27.75, facingDeg: 180 },
  { id: 'WP_mess_seat_15', zone: 'mess', kind: 'seat', level: 0, x: -22, y: 0, z: 26.25, facingDeg: 0 },
  { id: 'WP_mess_seat_16', zone: 'mess', kind: 'seat', level: 0, x: -22, y: 0, z: 27.75, facingDeg: 180 },
  { id: 'WP_mess_seat_17', zone: 'mess', kind: 'seat', level: 0, x: -21, y: 0, z: 26.25, facingDeg: 0 },
  { id: 'WP_mess_seat_18', zone: 'mess', kind: 'seat', level: 0, x: -21, y: 0, z: 27.75, facingDeg: 180 },
  { id: 'WP_mess_seat_19', zone: 'mess', kind: 'seat', level: 0, x: -20, y: 0, z: 26.25, facingDeg: 0 },
  { id: 'WP_mess_seat_20', zone: 'mess', kind: 'seat', level: 0, x: -20, y: 0, z: 27.75, facingDeg: 180 },
  { id: 'WP_mess_station_1', zone: 'mess', kind: 'station', level: 0, x: -26, y: 0, z: 28.8, facingDeg: 0, role: 'coffee' },
  { id: 'WP_mess_entry_1', zone: 'mess', kind: 'entry', level: 0, x: -22, y: 0, z: 21.4, facingDeg: 0 },
  { id: 'WP_lounge_seat_1', zone: 'lounge', kind: 'seat', level: 0, x: -1.5, y: 0, z: 26.7, facingDeg: 0, activity: 'chess' },
  { id: 'WP_lounge_seat_2', zone: 'lounge', kind: 'seat', level: 0, x: -1.5, y: 0, z: 28.3, facingDeg: 180, activity: 'chess' },
  { id: 'WP_lounge_seat_3', zone: 'lounge', kind: 'seat', level: 0, x: -8, y: 0, z: 24.2, facingDeg: 0 },
  { id: 'WP_lounge_seat_4', zone: 'lounge', kind: 'seat', level: 0, x: -7, y: 0, z: 24.2, facingDeg: 0 },
  { id: 'WP_lounge_seat_5', zone: 'lounge', kind: 'seat', level: 0, x: -4.6, y: 0, z: 26.2, facingDeg: 270 },
  { id: 'WP_lounge_entry_1', zone: 'lounge', kind: 'entry', level: 0, x: -6, y: 0, z: 21.4, facingDeg: 0 },
  { id: 'WP_comms_desk_station_1', zone: 'comms_desk', kind: 'station', level: 0, x: 6, y: 0, z: 28.2, facingDeg: 0, activity: 'ham_radio', favoredBy: ['crew_001'] },
  { id: 'WP_comms_desk_entry_1', zone: 'comms_desk', kind: 'entry', level: 0, x: 16, y: 0, z: 21.4, facingDeg: 0 },
  { id: 'WP_quarters_seat_1', zone: 'quarters', kind: 'seat', level: 1, x: -52, y: 4.2, z: 28.6, facingDeg: 0, activity: 'desk', crewId: 'crew_001' },
  { id: 'WP_quarters_idle_1', zone: 'quarters', kind: 'idle', level: 1, x: -56.4, y: 4.2, z: 27.6, facingDeg: 0, activity: 'sleep', crewId: 'crew_001' },
  { id: 'WP_quarters_entry_1', zone: 'quarters', kind: 'entry', level: 1, x: -50.5, y: 4.2, z: 23.4, facingDeg: 0, crewId: 'crew_001' },
  { id: 'WP_quarters_seat_2', zone: 'quarters', kind: 'seat', level: 1, x: -42, y: 4.2, z: 28.6, facingDeg: 0, activity: 'desk', crewId: 'crew_002' },
  { id: 'WP_quarters_idle_2', zone: 'quarters', kind: 'idle', level: 1, x: -46.4, y: 4.2, z: 27.6, facingDeg: 0, activity: 'sleep', crewId: 'crew_002' },
  { id: 'WP_quarters_entry_2', zone: 'quarters', kind: 'entry', level: 1, x: -40.5, y: 4.2, z: 23.4, facingDeg: 0, crewId: 'crew_002' },
  { id: 'WP_quarters_station_1', zone: 'quarters', kind: 'station', level: 1, x: -44.2, y: 4.2, z: 29, facingDeg: 0, activity: 'piano', crewId: 'crew_002' },
  { id: 'WP_quarters_seat_3', zone: 'quarters', kind: 'seat', level: 1, x: -32, y: 4.2, z: 28.6, facingDeg: 0, activity: 'desk', crewId: 'crew_003' },
  { id: 'WP_quarters_idle_3', zone: 'quarters', kind: 'idle', level: 1, x: -36.4, y: 4.2, z: 27.6, facingDeg: 0, activity: 'sleep', crewId: 'crew_003' },
  { id: 'WP_quarters_entry_3', zone: 'quarters', kind: 'entry', level: 1, x: -30.5, y: 4.2, z: 23.4, facingDeg: 0, crewId: 'crew_003' },
  { id: 'WP_quarters_idle_4', zone: 'quarters', kind: 'idle', level: 1, x: -18, y: 4.2, z: 23, facingDeg: 180, activity: 'overlook' },
  { id: 'WP_quarters_idle_5', zone: 'quarters', kind: 'idle', level: 1, x: 10, y: 4.2, z: 23, facingDeg: 180, activity: 'overlook' },
  { id: 'WP_sim_cockpit_station_1', zone: 'sim_cockpit', kind: 'station', level: 0, x: -40.5, y: 0, z: 3, facingDeg: 270, device: 'capsule_hatch' },
  { id: 'WP_sim_cockpit_queue_1', zone: 'sim_cockpit', kind: 'queue', level: 0, x: -38.6, y: 0, z: 4.6, facingDeg: 270 },
  { id: 'WP_sim_cockpit_station_2', zone: 'sim_cockpit', kind: 'station', level: 0, x: -22.5, y: 0, z: 3, facingDeg: 270, device: 'motion_sim' },
  { id: 'WP_sim_cockpit_station_3', zone: 'sim_cockpit', kind: 'station', level: 0, x: -14.6, y: 0, z: 12, facingDeg: 270, device: 'module_hatch' },
  { id: 'WP_sim_cockpit_idle_1', zone: 'sim_cockpit', kind: 'idle', level: 0, x: -34, y: 0, z: 8, facingDeg: 0 },
  { id: 'WP_sim_cockpit_idle_2', zone: 'sim_cockpit', kind: 'idle', level: 0, x: -48, y: 0, z: 16.5, facingDeg: 180 },
  { id: 'WP_sim_cockpit_entry_1', zone: 'sim_cockpit', kind: 'entry', level: 0, x: -36, y: 0, z: -4.2, facingDeg: 0 },
  { id: 'WP_comms_desk_seat_1', zone: 'comms_desk', kind: 'seat', level: 0, x: -6.1, y: 0, z: 3.08, facingDeg: 215.71, role: 'console' },
  { id: 'WP_comms_desk_seat_2', zone: 'comms_desk', kind: 'seat', level: 0, x: -7.32, y: 0, z: 4.6, facingDeg: 247.14, role: 'console' },
  { id: 'WP_comms_desk_seat_3', zone: 'comms_desk', kind: 'seat', level: 0, x: -7.56, y: 0, z: 6.54, facingDeg: 278.57, role: 'console' },
  { id: 'WP_comms_desk_seat_4', zone: 'comms_desk', kind: 'seat', level: 0, x: -6.76, y: 0, z: 8.31, facingDeg: 310, role: 'console' },
  { id: 'WP_comms_desk_seat_5', zone: 'comms_desk', kind: 'seat', level: 0, x: -5.15, y: 0, z: 9.41, facingDeg: 341.43, role: 'console' },
  { id: 'WP_comms_desk_seat_6', zone: 'comms_desk', kind: 'seat', level: 0, x: -3.2, y: 0, z: 9.51, facingDeg: 12.86, role: 'console' },
  { id: 'WP_comms_desk_seat_7', zone: 'comms_desk', kind: 'seat', level: 0, x: -1.49, y: 0, z: 8.58, facingDeg: 44.29, role: 'console' },
  { id: 'WP_comms_desk_idle_1', zone: 'comms_desk', kind: 'idle', level: 0, x: -4, y: 0, z: 9, facingDeg: 0 },
  { id: 'WP_comms_desk_entry_2', zone: 'comms_desk', kind: 'entry', level: 0, x: -4, y: 0, z: -4, facingDeg: 0 },
  { id: 'WP_robotics_bay_seat_1', zone: 'robotics_bay', kind: 'seat', level: 0, x: 17, y: 0, z: 17.4, facingDeg: 180, role: 'arm_operator' },
  { id: 'WP_robotics_bay_station_1', zone: 'robotics_bay', kind: 'station', level: 0, x: 13.5, y: 0, z: 9, facingDeg: 90, role: 'ground_spotter' },
  { id: 'WP_robotics_bay_entry_1', zone: 'robotics_bay', kind: 'entry', level: 0, x: 12, y: 0, z: 3.4, facingDeg: 0 },
  { id: 'WP_lunar_surface_station_1', zone: 'lunar_surface', kind: 'station', level: 0, x: 32, y: 0, z: 8, facingDeg: 45, activity: 'sampling' },
  { id: 'WP_lunar_surface_station_2', zone: 'lunar_surface', kind: 'station', level: 0, x: 40, y: 0, z: 15, facingDeg: 225, activity: 'rover_ops' },
  { id: 'WP_lunar_surface_seat_1', zone: 'lunar_surface', kind: 'seat', level: 0, x: 28.2, y: 0, z: 19.3, facingDeg: 0 },
  { id: 'WP_lunar_surface_idle_1', zone: 'lunar_surface', kind: 'idle', level: 0, x: 36, y: 0, z: 3, facingDeg: 0 },
  { id: 'WP_lunar_surface_entry_1', zone: 'lunar_surface', kind: 'entry', level: 0, x: 36, y: 0, z: 0.2, facingDeg: 0 },
  { id: 'WP_workshop_station_1', zone: 'workshop', kind: 'station', level: 0, x: 56.6, y: 0, z: 4, facingDeg: 90, activity: 'bench_work' },
  { id: 'WP_workshop_station_2', zone: 'workshop', kind: 'station', level: 0, x: 56.6, y: 0, z: 8.5, facingDeg: 90, activity: 'bench_work' },
  { id: 'WP_workshop_station_3', zone: 'workshop', kind: 'station', level: 0, x: 56.6, y: 0, z: 13, facingDeg: 90, activity: 'bench_work' },
  { id: 'WP_workshop_idle_1', zone: 'workshop', kind: 'idle', level: 0, x: 52, y: 0, z: 10, facingDeg: 90 },
  { id: 'WP_workshop_entry_1', zone: 'workshop', kind: 'entry', level: 0, x: 48, y: 0, z: 10, facingDeg: 90 },
  { id: 'WP_centrifuge_station_1', zone: 'centrifuge', kind: 'station', level: 0, x: 41.2, y: 0, z: -11.4, facingDeg: 180, device: 'gondola_hatch' },
  { id: 'WP_centrifuge_seat_1', zone: 'centrifuge', kind: 'seat', level: 0, x: 46.2, y: 0, z: -13.5, facingDeg: 270, role: 'centrifuge_operator' },
  { id: 'WP_centrifuge_queue_1', zone: 'centrifuge', kind: 'queue', level: 0, x: 44.4, y: 0, z: -11, facingDeg: 180 },
  { id: 'WP_centrifuge_entry_1', zone: 'centrifuge', kind: 'entry', level: 0, x: 43.4, y: 0, z: -6.2, facingDeg: 180 },
  { id: 'WP_thermal_vac_idle_1', zone: 'thermal_vac', kind: 'idle', level: 0, x: 47, y: 0, z: -23, facingDeg: 90 },
  { id: 'WP_pool_nbl_seat_1', zone: 'pool_nbl', kind: 'seat', level: 0, x: -45, y: 0, z: -10.7, facingDeg: 180 },
  { id: 'WP_pool_nbl_seat_2', zone: 'pool_nbl', kind: 'seat', level: 0, x: -42, y: 0, z: -10.7, facingDeg: 180 },
  { id: 'WP_pool_nbl_station_1', zone: 'pool_nbl', kind: 'station', level: 0, x: -30.2, y: 0, z: -23.6, facingDeg: 0, activity: 'dive_entry' },
  { id: 'WP_pool_nbl_station_2', zone: 'pool_nbl', kind: 'station', level: 0, x: -35, y: -1.8, z: -19, facingDeg: 0, activity: 'eva_underwater' },
  { id: 'WP_pool_nbl_idle_1', zone: 'pool_nbl', kind: 'idle', level: 0, x: -49, y: 0, z: -9.2, facingDeg: 180, role: 'dive_instructor' },
  { id: 'WP_pool_nbl_entry_1', zone: 'pool_nbl', kind: 'entry', level: 0, x: -40, y: 0, z: -8.4, facingDeg: 180 },
  { id: 'WP_gym_station_1', zone: 'gym', kind: 'station', level: 0, x: -21, y: 0, z: -23.6, facingDeg: 180, activity: 'strength' },
  { id: 'WP_gym_station_2', zone: 'gym', kind: 'station', level: 0, x: -16.5, y: 0, z: -23.6, facingDeg: 180, activity: 'strength' },
  { id: 'WP_gym_seat_1', zone: 'gym', kind: 'seat', level: 0, x: -22, y: 0, z: -14.8, facingDeg: 180, activity: 'rowing', favoredBy: ['crew_001'] },
  { id: 'WP_gym_seat_2', zone: 'gym', kind: 'seat', level: 0, x: -20.4, y: 0, z: -14.8, facingDeg: 180, activity: 'rowing', favoredBy: ['crew_001'] },
  { id: 'WP_gym_seat_3', zone: 'gym', kind: 'seat', level: 0, x: -18.8, y: 0, z: -14.8, facingDeg: 180, activity: 'rowing', favoredBy: ['crew_001'] },
  { id: 'WP_gym_station_3', zone: 'gym', kind: 'station', level: 0, x: -15, y: 0, z: -14.8, facingDeg: 180, activity: 'running', favoredBy: ['crew_002'] },
  { id: 'WP_gym_station_4', zone: 'gym', kind: 'station', level: 0, x: -13.4, y: 0, z: -14.8, facingDeg: 180, activity: 'running', favoredBy: ['crew_002'] },
  { id: 'WP_gym_seat_4', zone: 'gym', kind: 'seat', level: 0, x: -10.4, y: 0, z: -14.9, facingDeg: 180, activity: 'cycling', favoredBy: ['crew_002'] },
  { id: 'WP_gym_seat_5', zone: 'gym', kind: 'seat', level: 0, x: -9.1, y: 0, z: -14.9, facingDeg: 180, activity: 'cycling', favoredBy: ['crew_002'] },
  { id: 'WP_gym_station_5', zone: 'gym', kind: 'station', level: 0, x: -7, y: 0, z: -22, facingDeg: 90, activity: 'bouldering', favoredBy: ['crew_003'] },
  { id: 'WP_gym_idle_1', zone: 'gym', kind: 'idle', level: 0, x: -18.5, y: 0, z: -19.6, facingDeg: 0, activity: 'stretching' },
  { id: 'WP_gym_entry_1', zone: 'gym', kind: 'entry', level: 0, x: -14, y: 0, z: -8.4, facingDeg: 180 },
  { id: 'WP_garden_lab_station_1', zone: 'garden_lab', kind: 'station', level: 0, x: 8, y: 0, z: -21.55, facingDeg: 180, activity: 'plant_care', favoredBy: ['crew_003'] },
  { id: 'WP_garden_lab_station_2', zone: 'garden_lab', kind: 'station', level: 0, x: 8, y: 0, z: -18.65, facingDeg: 180, activity: 'plant_care' },
  { id: 'WP_garden_lab_seat_1', zone: 'garden_lab', kind: 'seat', level: 0, x: 13.2, y: 0, z: -20, facingDeg: 90, activity: 'logging' },
  { id: 'WP_garden_lab_entry_1', zone: 'garden_lab', kind: 'entry', level: 0, x: 9, y: 0, z: -14.4, facingDeg: 180 },
]

/** Waypoints by id. */
export const WAYPOINT_BY_ID: ReadonlyMap<string, Waypoint> = new Map(WAYPOINTS.map((point) => [point.id, point]))
