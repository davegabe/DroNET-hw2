from __future__ import annotations
import numpy as np
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from src.simulation.simulator import Simulator

from src.utilities import config, utilities


class SimulatedEntity:
    """ A simulated entity keeps track of the simulation object, where you can access all the parameters
    of the simulation. No class of this type is directly instantiable.
    """

    def __init__(self, simulator: Simulator) -> None:
        self.simulator = simulator


# ------------------ Entities ----------------------
class Entity(SimulatedEntity):
    """ An entity in the environment, e.g. Drone, Event, Packet. It extends SimulatedEntity. """

    def __init__(self, identifier: int, coords: tuple[float, float], simulator: Simulator) -> None:
        super().__init__(simulator)
        self.identifier = identifier  # the id of the entity
        self.coords = coords  # the coordinates of the entity on the map

    def __eq__(self, other: Entity) -> bool:
        """ Entity objects are identified by their id. """
        if not isinstance(other, Entity):
            return False
        else:
            return other.identifier == self.identifier

    def __hash__(self) -> int:
        return hash((self.identifier, self.coords))


# ------------------ Event -----------------------
# Created in feel_event, not a big deal
class EventDict(TypedDict):
    coord: tuple[float, float]
    i_gen: int
    i_dead: int
    id: int


class Event(Entity):
    """ An event is any kind of event that the drone detects on the aoi. It is an Entity. """

    def __init__(self, coords: tuple, current_time: int, simulator: Simulator, deadline: int = -1):
        super().__init__(id(self), coords, simulator)
        self.current_time = current_time

        # One can specify the deadline or just consider as deadline now + EVENTS_DURATION
        # The deadline of an event represents the estimate of the drone that the event will be no more
        # interesting to monitor.
        self.deadline = current_time + self.simulator.event_duration if deadline == -1 else deadline

        # add metrics: all the events generated during the simulation
        # GENERATED_EVENTS
        if not coords == (-1, -1) and not current_time == -1:
            self.simulator.metrics.events.add(self)

    def to_json(self) -> EventDict:
        """ return the json repr of the obj """
        return {
            "coord": self.coords,
            "i_gen": self.current_time,
            "i_dead": self.deadline,
            "id": self.identifier
        }

    def is_expired(self, cur_step: int) -> bool:
        """ return true if the deadline expired """
        return cur_step > self.deadline

    def as_packet(self, time_step_creation: int, drone: Drone) -> DataPacket:
        """ build a packet out of the event, by default the packet has deadline set to that of the event
            so the packet dies at the same time of the event, then add the input drone as first hop
        """
        # Notice: called only when a packet is created

        pck = DataPacket(time_step_creation, self.simulator, event_ref=self)
        # if config.DEBUG_PRINT_PACKETS: print("data", pck, pck.src_drone, pck.dst_drone, self.current_time)
        pck.add_hop(drone)
        return pck

    def __repr__(self):
        return "Ev id:" + str(self.identifier) + " c:" + str(self.coords)


# ------------------ Packet ----------------------
class PacketJSON(TypedDict):
    coord: tuple[float, float]
    i_gen: int
    i_dead: int
    id: int
    TTL: int
    id_event: int


class Packet(Entity):
    """ A packet is an object created out of an event monitored on the aoi. """

    def __init__(self, time_step_creation: int, simulator: Simulator, event_ref: Event | None = None):
        """ the event associated to the packet, time step in which the packet was created
         as for now, every packet is an event. """

        event_ref_crafted = event_ref if event_ref is not None else Event((-1, -1), -1,
                                                                          simulator)  # default event if packet is not associated to the event

        # id(self) is the id of this instance (unique for every new created packet),
        # the coordinates are those of the event
        super().__init__(id(self), event_ref_crafted.coords, simulator)

        self.time_step_creation = time_step_creation
        self.event_ref = event_ref_crafted
        self.__TTL = -1  # TTL is the number of hops that the packet crossed
        self.__max_TTL = self.simulator.packets_max_ttl
        self.number_retransmission_attempt = 0

        # self.hops = set()  # All the drones that have received/transmitted the packets
        self.last_2_hops: list[Drone] = []
        # add metrics: all the packets generated by the drones, either delivered or not (union of all the buffers)
        if event_ref is not None:
            self.add = self.simulator.metrics.drones_packets.add(self)

        self.optional_data: list[Any] = []  # list
        self.time_delivery: int = -1

        # if the packet was sent with move routing or not
        self.is_move_packet: bool = False

    def distance_from_depot(self) -> float:
        return utilities.euclidean_distance(self.simulator.depot_coordinates, self.coords)

    def age_of_packet(self, cur_step: int) -> int:
        return cur_step - self.time_step_creation

    def to_json(self) -> PacketJSON:
        """ return the json repr of the obj """

        return {"coord": self.coords,
                "i_gen": self.time_step_creation,
                "i_dead": self.event_ref.deadline,
                "id": self.identifier,
                "TTL": self.__TTL,
                "id_event": self.event_ref.identifier}

    def add_hop(self, drone: Drone):
        """ add a new hop in the packet """

        if len(self.last_2_hops) == 2:
            self.last_2_hops = self.last_2_hops[1:]  # keep just the last two HOPS
        self.last_2_hops.append(drone)

        # self.hops.add(drone.identifier)
        self.increase_TTL_hops()

    def increase_TTL_hops(self):
        self.__TTL += 1

    def increase_transmission_attempt(self):
        self.number_retransmission_attempt += 1

    def is_expired(self, cur_step: int) -> bool:
        """ a packet expires if the deadline of the event expires, or the maximum TTL is reached """
        return cur_step > self.event_ref.deadline

    def __repr__(self) -> str:
        packet_type = str(self.__class__).split(".")[-1].split("'")[0]
        return packet_type + "id:" + str(self.identifier) + " event id: " + str(
            self.event_ref.identifier) + " c:" + str(self.coords)

    def append_optional_data(self, data: Any):
        """ append optional data in the hello message to share with neigh drones infos """
        self.optional_data = data


class DataPacket(Packet):
    """ Basically a Packet"""

    def __init__(self, time_step_creation: int, simulator: Simulator, event_ref: Event | None = None):
        super().__init__(time_step_creation, simulator, event_ref)


class ACKPacket(Packet):
    def __init__(self, src_drone: Drone, dst_drone: Drone, simulator: Simulator, acked_packet: Packet, time_step_creation: int = -1):
        super().__init__(time_step_creation, simulator, None)
        self.acked_packet = acked_packet  # packet that the drone who creates it wants to ACK

        # source and destination of a packet
        self.src_drone = src_drone
        self.dst_drone = dst_drone


class HelloPacket(Packet):
    """ The hello message is responsible to give info about neighborhood """

    def __init__(self, src_drone: Drone, time_step_creation: int, simulator: Simulator, cur_pos: tuple[float, float], speed, next_target: tuple[float, float], link_holding_timer: float = 0, one_hop_neighbors=[], two_hop_neighbors=dict()):
        super().__init__(time_step_creation, simulator, None)
        self.cur_pos = cur_pos
        self.speed = speed
        self.next_target = next_target
        self.src_drone = src_drone  # don't use this

        self.link_holding_timer = link_holding_timer
        self.sequence_number = src_drone.sequence_number

        # increment the sequence number of the drone
        src_drone.sequence_number = src_drone.sequence_number + 1

        # list of neighbors
        self.one_hop_neighbors = one_hop_neighbors  # one hop neighbors N1
        self.two_hop_neighbors = two_hop_neighbors  # two hop neighbors N2

# ------------------ Drone ----------------------
class Drone(Entity):

    def __init__(self, identifier: int, path: list[tuple[float, float]], depot: Depot, simulator: Simulator, speed: float = 1):

        super().__init__(identifier, path[0], simulator)

        self.depot = depot
        self.path = path
        self.speed = speed
        self.sensing_range = self.simulator.drone_sen_range
        self.communication_range = self.simulator.drone_com_range
        self.buffer_max_size = self.simulator.drone_max_buffer_size
        self.residual_energy = self.simulator.drone_max_energy
        self.come_back_to_mission = False  # if i'm coming back to my applicative mission
        self.last_move_routing = False  # if in the last step i was moving to depot

        # dynamic parameters
        self.tightest_event_deadline: float = np.nan  # used later to check if there is an event that is about to expire
        self.current_waypoint = 0

        self.__buffer = []  # contains the packets

        self.distance_from_depot = 0
        self.move_routing = False  # if true, it moves to the depot

        # drone state
        self.power = 1

        # hello interval parameters
        self.link_holding_timer: float = 0
        self.tau: float = 0.5
        self.hello_interval: float = 1

        # array distance from other drones
        self.dist_t1 = 2030 * np.ones(self.simulator.n_drones)
        self.t1 = np.zeros(self.simulator.n_drones)
        self.dist_t2 = 2030 * np.ones(self.simulator.n_drones)
        self.t2 = np.zeros(self.simulator.n_drones)

        # sequence number
        self.sequence_number = 0

        # one hop neighbors
        self.one_hop_neighbors: list[Drone] = []
        self.prev_one_hop_neighbors: list[Drone] = []
        # two hop neighbors is a dict {drone.identifier: [list of neighbors]}
        self.two_hop_neighbors: dict[int, list[Drone]] = {}

        # setup drone routing algorithm
        self.routing_algorithm = self.simulator.routing_algorithm.value(self, self.simulator)

        # drone state simulator

        # last mission coord to restore the mission after movement
        self.last_mission_coords = None

    def update_battery(self, time_step: int):
        rand = np.random.uniform(0, self.simulator.drone_max_energy / self.simulator.len_simulation)
        self.residual_energy = self.residual_energy - rand


    def calc_distances(self, neighbor_drones: list[Drone]):
        """
        Calculate the distances between the current drone and the neighbors
        """
        for neighbor in neighbor_drones:
            # calculate the distance between the current drone and the neighbor
            self.dist_t2[neighbor.identifier] = np.sqrt(
                (self.coords[0] - neighbor.coords[0]) ** 2 + (self.coords[1] - neighbor.coords[1]) ** 2)
            self.t2[neighbor.identifier] = self.simulator.cur_step

    def update_hello_interval(self, neighbors: list[Drone]):
        """
        Update the hello interval of the current drone
        """
        if len(neighbors) == 0:
            return

        # calculate the distances between the current drone and the neighbors
        self.calc_distances(neighbors)

        # calculate the link duration
        link_duration = np.zeros(len(neighbors))
        for i in range(len(neighbors)):
            delta = self.dist_t2[i] - self.dist_t1[i]
            if delta > 0:
                link_duration[i] = np.abs(self.communication_range - self.dist_t2[i]) / \
                    (delta / (self.t2[i] - self.t1[i]))
            else:
                link_duration[i] = self.dist_t2[i] / self.speed

        # link holding timer
        self.link_holding_timer = np.nanmax(link_duration) # type: ignore # TODO: better typing(?)

        # update the hello interval
        self.hello_interval = np.ceil(self.tau * self.link_holding_timer) # ceil to avoid 0

        # t1 = t2
        self.t1 = self.t2.copy()
        self.dist_t1 = self.dist_t2.copy()

    def update_packets(self, cur_step: int):
        """
        Removes the expired packets from the buffer

        @param cur_step: Integer representing the current time step
        @return:
        """
        to_remove_packets = 0
        tmp_buffer = []
        self.tightest_event_deadline = np.nan

        for pck in self.__buffer:
            if not pck.is_expired(cur_step):
                tmp_buffer.append(pck)  # append again only if it is not expired
                self.tightest_event_deadline = np.nanmin([self.tightest_event_deadline, pck.event_ref.deadline])

            else:

                to_remove_packets += 1

                if self.simulator.routing_algorithm.name not in "GEO" "RND" "GEOS":

                    feedback = -1
                    current_drone = self

                    for drone in self.simulator.drones:
                        drone.routing_algorithm.feedback(current_drone,
                                                         pck.event_ref.identifier,
                                                         self.simulator.event_duration,
                                                         feedback)
        self.__buffer = tmp_buffer

        if self.buffer_length() == 0:
            self.move_routing = False

    def packet_is_expiring(self, cur_step: int) -> bool:
        """ return true if exist a packet that is expiring and must be returned to the depot as soon as possible
            -> start to move manually to the depot.

            This method is optional, there is flag src.utilities.config.ROUTING_IF_EXPIRING
        """
        time_to_depot = self.distance_from_depot / self.speed
        event_time_to_dead = (self.tightest_event_deadline - cur_step) * self.simulator.time_step_duration
        return event_time_to_dead - 5 < time_to_depot <= event_time_to_dead  # 5 seconds of tolerance

    def next_move_to_mission_point(self) -> tuple[float, float]:
        """ get the next future position of the drones, according the mission """
        current_waypoint = self.current_waypoint
        if current_waypoint >= len(self.path) - 1:
            current_waypoint = -1

        p0 = self.coords
        p1 = self.path[current_waypoint + 1]
        all_distance = utilities.euclidean_distance(p0, p1)
        distance = self.simulator.time_step_duration * self.speed
        if all_distance == 0 or distance == 0:
            return self.path[current_waypoint]

        t = distance / all_distance
        if t >= 1:
            return self.path[current_waypoint]
        elif t <= 0:
            print("Error move drone, ratio < 0")
            exit(1)
        else:
            return ((1 - t) * p0[0] + t * p1[0]), ((1 - t) * p0[1] + t * p1[1])

    def feel_event(self, cur_step: int):
        """
        feel a new event, and adds the packet relative to it, in its buffer.
            if the drones is doing movement the packet is not added in the buffer
         """

        ev = Event(self.coords, cur_step, self.simulator)  # the event
        pk = ev.as_packet(cur_step, self)  # the packet of the event
        if not self.move_routing and not self.come_back_to_mission:
            self.__buffer.append(pk)
            self.simulator.metrics.all_data_packets_in_simulation += 1
        else:  # store the events that are missing due to movement routing
            self.simulator.metrics.events_not_listened.add(ev)

    def accept_packets(self, packets: list[DataPacket]):
        """ Self drone adds packets of another drone, when it feels it passing by. """

        for packet in packets:
            # add if not notified yet, else don't, proprietary drone will delete all packets, but it is ok
            # because they have already been notified by someone already

            if not self.is_known_packet(packet):
                self.__buffer.append(packet)

    def routing(self, drones: list[Drone], depot: Depot, cur_step: int):
        """ do the routing """
        self.distance_from_depot = utilities.euclidean_distance(self.depot.coords, self.coords)
        self.routing_algorithm.routing(depot, drones, cur_step)

    def move(self, time: float):
        """ Move the drone to the next point if self.move_routing is false, else it moves towards the depot. 

            time -> time_step_duration (how much time between two simulation frame)
        """
        if self.move_routing or self.come_back_to_mission:
            # metrics: number of time steps on active routing (movement) a counter that is incremented each time
            # drone is moving to the depot for active routing, i.e., move_routing = True
            # or the drone is coming back to its mission
            self.simulator.metrics.time_on_active_routing += 1

        if self.move_routing:
            if not self.last_move_routing:  # this is the first time that we are doing move-routing
                self.last_mission_coords = self.coords

            self.__move_to_depot(time)
        else:
            if self.last_move_routing:  # I'm coming back to the mission
                self.come_back_to_mission = True

            self.__move_to_mission(time)

            # metrics: number of time steps on mission, incremented each time drone is doing sensing mission
            self.simulator.metrics.time_on_mission += 1

        # set the last move routing
        self.last_move_routing = self.move_routing

    def is_full(self) -> bool:
        """ Returns True if the drone buffer is full. """
        return self.buffer_length() == self.buffer_max_size

    def is_known_packet(self, packet: DataPacket) -> bool:
        """ Returns True if drone has already a similar packet (i.e., referred to the same event).  """
        for pk in self.__buffer:
            if pk.event_ref == packet.event_ref:
                return True
        return False

    def empty_buffer(self):
        """ Empties the buffer. """
        self.__buffer = []

    def all_packets(self) -> list[DataPacket]:
        """ Returns all the packets in the buffer. """
        return self.__buffer

    def buffer_length(self) -> int:
        """ Returns the length of the buffer. """
        return len(self.__buffer)

    def remove_packets(self, packets: list[Packet]):
        """ Removes the packets from the buffer. """
        for packet in packets:
            if packet in self.__buffer:
                self.__buffer.remove(packet)
                if config.DEBUG:
                    print("ROUTING del: drone: " + str(self.identifier) + " - removed a packet id: " + str(
                        packet.identifier))

    def next_target(self) -> tuple[float, float]:
        """ Returns the next target of the drone. """
        if self.move_routing:
            return self.depot.coords
        elif self.come_back_to_mission:
            return self.last_mission_coords  # type: ignore # TODO: better typing(?)
        else:
            if self.current_waypoint >= len(self.path) - 1:  # reached the end of the path, start back to 0
                return self.path[0]
            else:
                return self.path[self.current_waypoint + 1]

    def __move_to_mission(self, time: float):
        """ When invoked the drone moves on the map. TODO: Add comments and clean.
            time -> time_step_duration (how much time between two simulation frame)
        """
        if self.current_waypoint >= len(self.path) - 1:
            self.current_waypoint = -1

        p0 = self.coords
        if self.come_back_to_mission:  # after move
            p1 = self.last_mission_coords
        else:
            p1 = self.path[self.current_waypoint + 1]

        all_distance = utilities.euclidean_distance(p0, p1)  # type: ignore  # TODO: better typing(?)
        distance = time * self.speed
        if all_distance == 0 or distance == 0:
            self.__update_position(p1)  # type: ignore  # TODO: better typing(?)
            return

        t = distance / all_distance
        if t >= 1:
            self.__update_position(p1)  # type: ignore  # TODO: better typing(?)
        elif t <= 0:
            print("Error move drone, ratio < 0")
            exit(1)
        else:
            self.coords = (((1 - t) * p0[0] + t * p1[0]), ((1 - t) * p0[1] + t * p1[1])) # type: ignore  # TODO: better typing(?)

    def __update_position(self, p1: tuple[float, float]):
        """ Updates the position of the drone. """
        if self.come_back_to_mission:
            self.come_back_to_mission = False
            self.coords = p1
        else:
            self.current_waypoint += 1
            self.coords = self.path[self.current_waypoint]

    def __move_to_depot(self, time: float):
        """ When invoked the drone moves to the depot. TODO: Add comments and clean.
            time -> time_step_duration (how much time between two simulation frame)
        """
        p0 = self.coords
        p1 = self.depot.coords

        all_distance = utilities.euclidean_distance(p0, p1)
        distance = time * self.speed
        if all_distance == 0:
            self.move_routing = False
            return

        t = distance / all_distance

        if t >= 1:
            self.coords = p1  # with the next step you would surpass the target
        elif t <= 0:
            print("Error routing move drone, ratio < 0")
            exit(1)
        else:
            self.coords = (((1 - t) * p0[0] + t * p1[0]), ((1 - t) * p0[1] + t * p1[1]))

    def __repr__(self) -> str:
        return "Drone " + str(self.identifier)

    def __hash__(self) -> int:
        return hash(self.identifier)


# ------------------ Depot ----------------------
class Depot(Drone):
    """ The depot is an Entity. """

    def __init__(self, coords: tuple[float, float], path: list[tuple[float, float]], speed: float, communication_range, simulator: Simulator):  # TODO: type
        super().__init__(id(self), path, self, simulator, speed)
        self.communication_range = communication_range
        self.path = path

        self.__buffer: list[Packet] = list()  # also with duplicated packets

    def all_packets(self) -> list[Packet]:
        return self.__buffer

    def transfer_notified_packets(self, current_drone: Drone, cur_step: int):
        """ function called when a drone wants to offload packets to the depot """

        packets_to_offload = current_drone.all_packets()
        self.__buffer += packets_to_offload

        for pck in packets_to_offload:

            if self.simulator.routing_algorithm.name not in "GEO" "RND" "GEOS":

                feedback = 1
                delivery_delay = cur_step - pck.event_ref.current_time

                for drone in self.simulator.drones:
                    drone.routing_algorithm.feedback(current_drone,
                                                     pck.event_ref.identifier,
                                                     delivery_delay,
                                                     feedback)
            # print(f"DEPOT -> Drone {current_drone.identifier} packet: {pck.event_ref} total packets in sim: {len(self.simulator.metrics.drones_packets_to_depot)}")

            # add metrics: all the packets notified to the depot
            self.simulator.metrics.drones_packets_to_depot.add((pck, cur_step))
            self.simulator.metrics.drones_packets_to_depot_list.append((pck, cur_step))
            pck.time_delivery = cur_step

# ------------------ Environment ----------------------
class Environment(SimulatedEntity):
    """ The environment is an entity that represents the area of interest on which events are generated.
     WARNING this corresponds to an old view we had, according to which the events are generated on the map at
     random and then maybe felt from the drones. Now events are generated on the drones that they feel with
     a certain probability."""

    def __init__(self, width: int, height: int, simulator: Simulator):
        super().__init__(simulator)

        self.depot: Depot | None = None
        self.drones: list[Drone] = []
        self.width = width
        self.height = height

        self.event_generator = EventGenerator(height, width, simulator)
        self.active_events = []  # TODO: type

    def add_drones(self, drones: list[Drone]):
        """ add a list of drones in the env """
        self.drones = drones

    def add_depot(self, depot: Depot):
        """ add depot in the env """
        self.depot = depot


class EventGenerator(SimulatedEntity):

    def __init__(self, height: int, width: int, simulator: Simulator):
        """ uniform event generator """
        super().__init__(simulator)
        self.height = height
        self.width = width

    def uniform_event_generator(self) -> tuple[int, int]:
        """ generates an event in the map """
        x = self.simulator.rnd_env.randint(0, self.height)
        y = self.simulator.rnd_env.randint(0, self.width)
        return x, y

    def poisson_event_generator(self):
        """ generates an event in the map """
        pass
