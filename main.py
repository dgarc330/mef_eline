"""Main module of kytos/mef_eline Kytos Network Application.

NApp to provision circuits from user request.
"""
from flask import jsonify, request
from werkzeug.exceptions import BadRequest

from kytos.core import KytosNApp, log, rest
from kytos.core.events import KytosEvent
from kytos.core.helpers import listen_to
from kytos.core.interface import TAG, UNI
from kytos.core.link import Link
from napps.kytos.mef_eline.models import EVC, DynamicPathManager
from napps.kytos.mef_eline.scheduler import CircuitSchedule, Scheduler
from napps.kytos.mef_eline.storehouse import StoreHouse


class Main(KytosNApp):
    """Main class of amlight/mef_eline NApp.

    This class is the entry point for this napp.
    """

    def setup(self):
        """Replace the '__init__' method for the KytosNApp subclass.

        The setup method is automatically called by the controller when your
        application is loaded.

        So, if you have any setup routine, insert it here.
        """
        # object used to scheduler circuit events
        self.sched = Scheduler()

        # object to save and load circuits
        self.storehouse = StoreHouse(self.controller)

        # set the controller that will manager the dynamic paths
        DynamicPathManager.set_controller(self.controller)

        # dictionary of EVCs created
        self.circuits = {}

    def execute(self):
        """Execute once when the napp is running."""

    def shutdown(self):
        """Execute when your napp is unloaded.

        If you have some cleanup procedure, insert it here.
        """

    @rest('/v2/evc/', methods=['GET'])
    def list_circuits(self):
        """Endpoint to return all circuits stored."""
        circuits = self.storehouse.get_data()
        if not circuits:
            return jsonify({}), 200

        return jsonify(circuits), 200

    @rest('/v2/evc/<circuit_id>', methods=['GET'])
    def get_circuit(self, circuit_id):
        """Endpoint to return a circuit based on id."""
        circuits = self.storehouse.get_data()
        try:
            result = circuits[circuit_id]
            status = 200
        except KeyError:
            result = {'response': f'circuit_id {circuit_id} not found'}
            status = 404

        return jsonify(result), status

    @rest('/v2/evc/', methods=['POST'])
    def create_circuit(self):
        """Try to create a new circuit.

        Firstly, for EVPL: E-Line NApp verifies if UNI_A's requested C-VID and
        UNI_Z's requested C-VID are available from the interfaces' pools. This
        is checked when creating the UNI object.

        Then, E-Line NApp requests a primary and a backup path to the
        Pathfinder NApp using the attributes primary_links and backup_links
        submitted via REST

        # For each link composing paths in #3:
        #  - E-Line NApp requests a S-VID available from the link VLAN pool.
        #  - Using the S-VID obtained, generate abstract flow entries to be
        #    sent to FlowManager

        Push abstract flow entries to FlowManager and FlowManager pushes
        OpenFlow entries to datapaths

        E-Line NApp generates an event to notify all Kytos NApps of a new EVC
        creation

        Finnaly, notify user of the status of its request.
        """
        # Try to create the circuit object
        data = request.get_json()

        if not data:
            return jsonify("Bad request: The request do not have a json."), 400

        try:
            evc = self.evc_from_dict(data)
        except ValueError as exception:
            return jsonify("Bad request: {}".format(exception)), 400

        # verify duplicated evc
        if self.is_duplicated_evc(evc):
            return jsonify("Not Acceptable: This evc already exists."), 409

        # store circuit in dictionary
        self.circuits[evc.id] = evc

        # save circuit
        self.storehouse.save_evc(evc)

        # Schedule the circuit deploy
        self.sched.add(evc)

        # Circuit has no schedule, deploy now
        if not evc.circuit_scheduler:
            evc.deploy()

        # Notify users
        event = KytosEvent(name='kytos.mef_eline.created',
                           content=evc.as_dict())
        self.controller.buffers.app.put(event)

        return jsonify({"circuit_id": evc.id}), 201

    @rest('/v2/evc/<circuit_id>', methods=['PATCH'])
    def update(self, circuit_id):
        """Update a circuit based on payload.

        The EVC required attributes (name, uni_a, uni_z) can't be updated.
        """
        try:
            evc = self.circuits[circuit_id]
            data = request.get_json()
            evc.update(**data)
        except ValueError as exception:
            result = {'response': 'Bad Request: {}'.format(exception)}
            status = 400
        except TypeError:
            result = {'response': 'Content-Type must be application/json'}
            status = 415
        except BadRequest:
            response = 'Bad Request: The request is not a valid JSON.'
            result = {'response': response}
            status = 400
        except KeyError:
            result = {'response': f'circuit_id {circuit_id} not found'}
            status = 404
        else:
            evc.sync()
            result = {evc.id: evc.as_dict()}
            status = 200

        return jsonify(result), status

    @rest('/v2/evc/<circuit_id>', methods=['DELETE'])
    def delete_circuit(self, circuit_id):
        """Remove a circuit.

        First, the flows are removed from the switches, and then the EVC is
        disabled.
        """
        try:
            evc = self.circuits[circuit_id]
        except KeyError:
            result = {'response': f'circuit_id {circuit_id} not found'}
            status = 404
        else:
            log.info(f'Removing {circuit_id}')
            if evc.archived:
                result = {'response': f'Circuit {circuit_id} already removed'}
                status = 404
            else:
                evc.remove_current_flows()
                evc.deactivate()
                evc.disable()
                self.sched.remove(evc)
                evc.archive()
                evc.sync()
                result = {'response': f'Circuit {circuit_id} removed'}
                status = 200

        return jsonify(result), status

    def is_duplicated_evc(self, evc):
        """Verify if the circuit given is duplicated with the stored evcs.

        Args:
            evc (EVC): circuit to be analysed.

        Returns:
            boolean: True if the circuit is duplicated, otherwise False.

        """
        for circuit in self.circuits.values():
            if not circuit.archived and circuit == evc:
                return True
        return False

    @listen_to('kytos/topology.link_up')
    def handle_link_up(self, event):
        """Change circuit when link is up or end_maintenance."""
        for evc in self.circuits.values():
            if evc.is_enabled() and not evc.archived:
                evc.handle_link_up(event.content['link'])

    @listen_to('kytos/topology.link_down')
    def handle_link_down(self, event):
        """Change circuit when link is down or under_mantenance."""
        for evc in self.circuits.values():
            if evc.is_affected_by_link(event.content['link']):
                log.info('handling evc %s' % evc)
                evc.handle_link_down()

    def evc_from_dict(self, evc_dict):
        """Convert some dict values to instance of EVC classes.

        This method will convert: [UNI, Link]
        """
        data = evc_dict.copy()  # Do not modify the original dict

        for attribute, value in data.items():

            if 'uni' in attribute:
                try:
                    data[attribute] = self.uni_from_dict(value)
                except ValueError as exc:
                    raise ValueError(f'Error creating UNI: {exc}')

            if attribute == 'circuit_scheduler':
                data[attribute] = []
                for schedule in value:
                    data[attribute].append(CircuitSchedule.from_dict(schedule))

            if 'link' in attribute:
                if value:
                    data[attribute] = self.link_from_dict(value)

            if 'path' in attribute and attribute != 'dynamic_backup_path':
                if value:
                    data[attribute] = [self.link_from_dict(link)
                                       for link in value]

        return EVC(self.controller, **data)

    def uni_from_dict(self, uni_dict):
        """Return a UNI object from python dict."""
        if uni_dict is None:
            return False

        interface_id = uni_dict.get("interface_id")
        interface = self.controller.get_interface_by_id(interface_id)
        if interface is None:
            raise ValueError(f'Could not instantiate interface {interface_id}')

        tag_dict = uni_dict.get("tag")
        tag = TAG.from_dict(tag_dict)
        if tag is False:
            raise ValueError(f'Could not instantiate tag from dict {tag_dict}')

        uni = UNI(interface, tag)

        return uni

    def link_from_dict(self, link_dict):
        """Return a Link object from python dict."""
        id_a = link_dict.get('endpoint_a').get('id')
        id_b = link_dict.get('endpoint_b').get('id')

        endpoint_a = self.controller.get_interface_by_id(id_a)
        endpoint_b = self.controller.get_interface_by_id(id_b)

        link = Link(endpoint_a, endpoint_b)
        if 'metadata' in link_dict:
            link.extend_metadata(link_dict.get('metadata'))

        s_vlan = link.get_metadata('s_vlan')
        if s_vlan:
            tag = TAG.from_dict(s_vlan)
            if tag is False:
                error_msg = f'Could not instantiate tag from dict {s_vlan}'
                raise ValueError(error_msg)
            link.update_metadata('s_vlan', tag)
        return link
