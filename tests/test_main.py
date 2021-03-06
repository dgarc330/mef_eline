"""Module to test the main napp file."""
import json
from unittest import TestCase
from unittest.mock import patch

from napps.kytos.mef_eline.main import Main
from tests.helpers import get_controller_mock


class TestMain(TestCase):
    """Test the Main class."""

    def setUp(self):
        """Execute steps before each tests.

        Set the server_name_url_url from kytos/mef_eline
        """
        self.server_name_url = 'http://localhost:8181/api/kytos/mef_eline'
        self.napp = Main(get_controller_mock())

    def test_get_event_listeners(self):
        """Verify all event listeners registered."""
        expected_events = ['kytos/core.shutdown',
                           'kytos/core.shutdown.kytos/mef_eline',
                           'kytos/topology.link_up',
                           'kytos/topology.link_down']
        actual_events = self.napp.listeners()

        for _event in expected_events:
            self.assertIn(_event, actual_events, '%s' % _event)

    def test_verify_api_urls(self):
        """Verify all APIs registered."""
        expected_urls = [
            ({}, {'OPTIONS', 'POST'},
             '/api/kytos/mef_eline/v2/evc/'),
            ({}, {'OPTIONS', 'HEAD', 'GET'},
             '/api/kytos/mef_eline/v2/evc/'),
            ({'circuit_id': '[circuit_id]'}, {'OPTIONS', 'DELETE'},
             '/api/kytos/mef_eline/v2/evc/<circuit_id>'),
            ({'circuit_id': '[circuit_id]'}, {'OPTIONS', 'HEAD', 'GET'},
             '/api/kytos/mef_eline/v2/evc/<circuit_id>'),
            ({'circuit_id': '[circuit_id]'}, {'OPTIONS', 'PATCH'},
             '/api/kytos/mef_eline/v2/evc/<circuit_id>')]
        urls = self.get_napp_urls(self.napp)
        self.assertEqual(expected_urls, urls)

    def test_list_without_circuits(self):
        """Test if list circuits return 'no circuit stored.'."""
        api = self.get_app_test_client(self.napp)
        url = f'{self.server_name_url}/v2/evc/'
        response = api.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.data.decode()), {})

    @patch('napps.kytos.mef_eline.storehouse.StoreHouse.get_data')
    def test_list_no_circuits_stored(self, storehouse_data_mock):
        """Test if list circuits return all circuits stored."""
        circuits = {}
        storehouse_data_mock.return_value = circuits

        api = self.get_app_test_client(self.napp)
        url = f'{self.server_name_url}/v2/evc/'

        response = api.get(url)
        expected_result = circuits
        self.assertEqual(json.loads(response.data), expected_result)

    @patch('napps.kytos.mef_eline.storehouse.StoreHouse.get_data')
    def test_list_with_circuits_stored(self, storehouse_data_mock):
        """Test if list circuits return all circuits stored."""
        circuits = {'1': {'name': 'circuit_1'},
                    '2': {'name': 'circuit_2'}}
        storehouse_data_mock.return_value = circuits

        api = self.get_app_test_client(self.napp)
        url = f'{self.server_name_url}/v2/evc/'

        response = api.get(url)
        expected_result = circuits
        self.assertEqual(json.loads(response.data), expected_result)

    @patch('napps.kytos.mef_eline.storehouse.StoreHouse.get_data')
    def test_circuit_with_valid_id(self, storehouse_data_mock):
        """Test if get_circuit return the circuit attributes."""
        circuits = {'1': {'name': 'circuit_1'},
                    '2': {'name': 'circuit_2'}}
        storehouse_data_mock.return_value = circuits

        api = self.get_app_test_client(self.napp)
        url = f'{self.server_name_url}/v2/evc/1'
        response = api.get(url)
        expected_result = circuits['1']
        self.assertEqual(json.loads(response.data), expected_result)

    @patch('napps.kytos.mef_eline.storehouse.StoreHouse.get_data')
    def test_circuit_with_invalid_id(self, storehouse_data_mock):
        """Test if get_circuit return invalid circuit_id."""
        circuits = {'1': {'name': 'circuit_1'},
                    '2': {'name': 'circuit_2'}}
        storehouse_data_mock.return_value = circuits

        api = self.get_app_test_client(self.napp)
        url = f'{self.server_name_url}/v2/evc/3'
        response = api.get(url)
        expected_result = {'response': 'circuit_id 3 not found'}
        self.assertEqual(json.loads(response.data), expected_result)

    @patch('napps.kytos.mef_eline.storehouse.StoreHouse.get_data')
    @patch('napps.kytos.mef_eline.scheduler.Scheduler.add')
    @patch('napps.kytos.mef_eline.main.Main.uni_from_dict')
    @patch('napps.kytos.mef_eline.storehouse.StoreHouse.save_evc')
    @patch('napps.kytos.mef_eline.main.EVC.as_dict')
    @patch('napps.kytos.mef_eline.models.EVC._validate')
    def test_create_a_circuit_case_1(self, *args):
        """Test create a new circuit."""
        (validate_mock, evc_as_dict_mock, save_evc_mock,
         uni_from_dict_mock, sched_add_mock, storehouse_data_mock) = args

        validate_mock.return_value = True
        save_evc_mock.return_value = True
        uni_from_dict_mock.side_effect = ['uni_a', 'uni_z']
        evc_as_dict_mock.return_value = {}
        sched_add_mock.return_value = True
        storehouse_data_mock.return_value = {}

        api = self.get_app_test_client(self.napp)
        url = f'{self.server_name_url}/v2/evc/'
        payload = {
                   "name": "my evc1",
                   "frequency": "* * * * *",
                   "uni_a": {
                     "interface_id": "00:00:00:00:00:00:00:01:1",
                     "tag": {
                       "tag_type": 1,
                       "value": 80
                     }
                   },
                   "uni_z": {
                     "interface_id": "00:00:00:00:00:00:00:02:2",
                     "tag": {
                       "tag_type": 1,
                       "value": 1
                     }
                   }
                 }

        response = api.post(url, data=json.dumps(payload),
                            content_type='application/json')
        current_data = json.loads(response.data)

        # verify expected result from request
        self.assertEqual(201, response.status_code, response.data)
        self.assertIn('circuit_id', current_data)

        # verify uni called
        uni_from_dict_mock.called_twice()
        uni_from_dict_mock.assert_any_call(payload['uni_z'])
        uni_from_dict_mock.assert_any_call(payload['uni_a'])

        # verify validation called
        validate_mock.assert_called_once()
        validate_mock.assert_called_with(frequency='* * * * *',
                                         name='my evc1',
                                         uni_a='uni_a',
                                         uni_z='uni_z')
        # verify save method is called
        save_evc_mock.assert_called_once()

        # verify evc as dict is called to save in the box
        evc_as_dict_mock.assert_called_once()
        # verify add circuit in sched
        sched_add_mock.assert_called_once()

    @staticmethod
    def get_napp_urls(napp):
        """Return the kytos/mef_eline urls.

        The urls will be like:

        urls = [
            (options, methods, url)
        ]

        """
        controller = napp.controller
        controller.api_server.register_napp_endpoints(napp)

        urls = []
        for rule in controller.api_server.app.url_map.iter_rules():
            options = {}
            for arg in rule.arguments:
                options[arg] = "[{0}]".format(arg)

            if f'{napp.username}/{napp.name}' in str(rule):
                urls.append((options, rule.methods, f'{str(rule)}'))

        return urls

    @staticmethod
    def get_app_test_client(napp):
        """Return a flask api test client."""
        napp.controller.api_server.register_napp_endpoints(napp)
        return napp.controller.api_server.app.test_client()

    def test_create_a_circuit_case_2(self):
        """Test create a new circuit trying to send request without a json."""
        api = self.get_app_test_client(self.napp)
        url = f'{self.server_name_url}/v2/evc/'

        response = api.post(url)
        current_data = json.loads(response.data)
        expected_data = 'Bad request: The request do not have a json.'

        self.assertEqual(400, response.status_code)
        self.assertEqual(current_data, expected_data)

    @patch('napps.kytos.mef_eline.scheduler.Scheduler.add')
    @patch('napps.kytos.mef_eline.main.Main.uni_from_dict')
    @patch('napps.kytos.mef_eline.storehouse.StoreHouse.save_evc')
    @patch('napps.kytos.mef_eline.models.EVC._validate')
    @patch('napps.kytos.mef_eline.main.EVC.as_dict')
    def test_create_circuit_already_enabled(self, *args):
        """Test create an already created circuit."""
        (evc_as_dict_mock, validate_mock, save_evc_mock,
         uni_from_dict_mock, sched_add_mock) = args

        validate_mock.return_value = True
        save_evc_mock.return_value = True
        sched_add_mock.return_value = True
        uni_from_dict_mock.side_effect = ['uni_a', 'uni_z', 'uni_a', 'uni_z']
        payload1 = {'name': 'circuit_1'}

        api = self.get_app_test_client(self.napp)
        payload2 = {
            "name": "my evc1",
            "frequency": "* * * * *",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {
                    "tag_type": 1,
                    "value": 80
                }
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {
                    "tag_type": 1,
                    "value": 1
                }
            }
        }

        evc_as_dict_mock.return_value = payload1
        response = api.post(f'{self.server_name_url}/v2/evc/',
                            data=json.dumps(payload1),
                            content_type='application/json')
        self.assertEqual(201, response.status_code)

        evc_as_dict_mock.return_value = payload2
        response = api.post(f'{self.server_name_url}/v2/evc/',
                            data=json.dumps(payload2),
                            content_type='application/json')
        self.assertEqual(201, response.status_code)

        response = api.post(f'{self.server_name_url}/v2/evc/',
                            data=json.dumps(payload2),
                            content_type='application/json')
        current_data = json.loads(response.data)
        expected_data = 'Not Acceptable: This evc already exists.'
        self.assertEqual(current_data, expected_data)
        self.assertEqual(409, response.status_code)
