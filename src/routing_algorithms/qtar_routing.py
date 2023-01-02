import numpy as np
from src.entities.uav_entities import DataPacket, Drone
from src.routing_algorithms.ADVANCED_routing import ADVANCED_Routing
from src.utilities import utilities as util


class QTARRouting(ADVANCED_Routing):

    def __init__(self, drone, simulator):
        ADVANCED_Routing.__init__(self, drone=drone, simulator=simulator)
        self.taken_actions = {}  # id event : (old_state, old_action)
        self.q_table = np.zeros(self.simulator.n_drones)
        self.A = 0.7  # importanza alla reward sul delay
        self.B = 0.2  # importanza alla reward sulla velocità
        self.C = 0.1  # importanza alla batteria

    def feedback(self, drone: Drone, id_event, delay, outcome):
        """
        Feedback returned when the packet arrives at the depot or
        Expire. This function have to be implemented in RL-based protocols ONLY
        @param drone: The drone that holds the packet
        @param id_event: The Event id
        @param delay: packet delay
        @param outcome: -1 if the packet expired; 1 if the packets has been delivered to the depot
        @return:
        """
        # Be aware, due to network errors we can give the same event to multiple drones and receive multiple
        # feedback for the same packet!!

        if id_event in self.taken_actions:
            state, action = self.taken_actions[id_event]
            #Sr = F2hop : VUi,f→Um > Vr
            

            # remove the entry, the action has received the feedback
            del self.taken_actions[id_event]

            # reward or update using the old state and the selected action at that time
            delay = delay / self.simulator.packets_max_ttl
            speed = 1  # drone.speed / self.simulator.drone_max_velocity
            energy = drone.residual_energy / self.simulator.drone_max_energy

            self.q_table[action] = self.A * delay + self.B * speed + self.C * energy

    def relay_selection(self, packet: DataPacket, drone_near_depot_id: int = -1) -> Drone:
        """
        This function returns the best relay to send packets.
        @param packet:
        @param opt_neighbors: a list of tuple (hello_packet, source_drone)
        @return: The best drone to use as relay
        """
        state = self.drone.identifier  # state is the drone id
        action: int = -1  # action is the drone id

        # potential good neighbors, ignore the ones that are too slow to reach the depot in time
        selected_drones = []
        # if there is a drone near the depot, select it
        if drone_near_depot_id != -1:
            selected_drones.append(self.simulator.drones[drone_near_depot_id])
        else:
            # otherwise select the neighbors that are faster than the required speed
            for one_hop_id, two_hop_neighbors in self.drone.two_hop_neighbors.items():
                one_hop_neighbor = self.simulator.drones[one_hop_id]
                for neighbor in two_hop_neighbors:
                    speed = util.two_hop_speed(self.drone, one_hop_neighbor, neighbor, self.simulator)
                    remaining_ttl = self.simulator.packets_max_ttl - (self.simulator.cur_step - packet.time_step_creation)
                    required_speed = util.compute_required_speed(neighbor, remaining_ttl , self.simulator)
                    if speed > required_speed:
                        selected_drones.append(neighbor)

        # select the best drone to relay the packet (the one with the highest q value) among the neighbors
        sorted_q_table = np.argsort(self.q_table)  # sorta gli indici a = [22,3,6] -> [1,2,0]
        neighborsId = [d.identifier for d in selected_drones]
        for droneId in sorted_q_table:
            # check if the drone is in the list of neighbors by identifier
            if droneId in neighborsId:
                action = droneId
                break

        # Store your current action --- you can add some stuff if needed to take a reward later
        self.taken_actions[packet.event_ref.identifier] = (state, action)

        return self.simulator.drones[action]