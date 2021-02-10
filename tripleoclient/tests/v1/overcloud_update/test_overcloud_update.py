#   Copyright 2015 Red Hat, Inc.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.
#

import mock

from osc_lib.tests.utils import ParserException
from tripleoclient import constants
from tripleoclient import exceptions
from tripleoclient.tests.v1.overcloud_update import fakes
from tripleoclient.v1 import overcloud_update


class TestOvercloudUpdatePrepare(fakes.TestOvercloudUpdatePrepare):

    def setUp(self):
        super(TestOvercloudUpdatePrepare, self).setUp()

        # Get the command object to test
        app_args = mock.Mock()
        app_args.verbose_level = 1
        self.cmd = overcloud_update.UpdatePrepare(self.app, app_args)

        uuid4_patcher = mock.patch('uuid.uuid4', return_value="UUID4")
        self.mock_uuid4 = uuid4_patcher.start()
        self.addCleanup(self.mock_uuid4.stop)

    @mock.patch('tripleoclient.utils.get_stack_output_item',
                autospec=True)
    @mock.patch('tripleoclient.utils.prompt_user_for_confirmation',
                return_value=True)
    @mock.patch('tripleoclient.v1.overcloud_deploy.DeployOvercloud.'
                '_get_undercloud_host_entry', autospec=True,
                return_value='192.168.0.1 uc.ctlplane.localhost uc.ctlplane')
    @mock.patch('tripleoclient.utils.get_stack',
                autospec=True)
    @mock.patch('tripleoclient.v1.overcloud_update.UpdatePrepare.log',
                autospec=True)
    @mock.patch('tripleoclient.workflows.package_update.update',
                autospec=True)
    @mock.patch('os.path.abspath')
    @mock.patch('yaml.safe_load')
    @mock.patch('shutil.copytree', autospec=True)
    @mock.patch('tripleoclient.v1.overcloud_deploy.DeployOvercloud.'
                '_deploy_tripleo_heat_templates_tmpdir', autospec=True)
    def test_update_out(self, mock_deploy, mock_copy, mock_yaml,
                        mock_abspath, mock_update, mock_logger,
                        mock_get_stack, mock_get_undercloud_host_entry,
                        mock_confirm, mock_get_stack_output_item):
        mock_stack = mock.Mock(parameters={'DeployIdentifier': ''})
        mock_stack.stack_name = 'overcloud'
        mock_get_stack.return_value = mock_stack
        mock_yaml.return_value = {'fake_container': 'fake_value'}

        argslist = ['--stack', 'overcloud', '--templates']

        verifylist = [
            ('stack', 'overcloud'),
            ('templates', constants.TRIPLEO_HEAT_TEMPLATES),
        ]

        parsed_args = self.check_parser(self.cmd, argslist, verifylist)
        with mock.patch('os.path.exists') as mock_exists, \
                mock.patch('os.path.isfile') as mock_isfile, \
                mock.patch('six.moves.builtins.open'):
            mock_exists.return_value = True
            mock_isfile.return_value = True
            self.cmd.take_action(parsed_args)
            mock_update.assert_called_once_with(
                self.app.client_manager,
                container='overcloud',
            )

    @mock.patch('tripleoclient.utils.get_stack_output_item',
                autospec=True)
    @mock.patch('tripleoclient.utils.prompt_user_for_confirmation',
                return_value=True)
    @mock.patch('tripleoclient.utils.get_stack',
                autospec=True)
    @mock.patch('tripleoclient.workflows.package_update.update',
                autospec=True)
    @mock.patch('os.path.abspath')
    @mock.patch('yaml.safe_load')
    @mock.patch('shutil.copytree', autospec=True)
    @mock.patch('tripleoclient.v1.overcloud_deploy.DeployOvercloud.'
                '_deploy_tripleo_heat_templates', autospec=True)
    def test_update_failed(self, mock_deploy, mock_copy, mock_yaml,
                           mock_abspath, mock_update,
                           mock_get_stack, mock_confirm,
                           mock_get_stack_output_item):
        mock_stack = mock.Mock(parameters={'DeployIdentifier': ''})
        mock_stack.stack_name = 'overcloud'
        mock_get_stack.return_value = mock_stack
        mock_update.side_effect = exceptions.DeploymentError()
        mock_yaml.return_value = {'fake_container': 'fake_value'}
        argslist = ['--stack', 'overcloud', '--templates', ]
        verifylist = [
            ('stack', 'overcloud'),
            ('templates', constants.TRIPLEO_HEAT_TEMPLATES),
        ]
        parsed_args = self.check_parser(self.cmd, argslist, verifylist)

        with mock.patch('os.path.exists') as mock_exists, \
                mock.patch('os.path.isfile') as mock_isfile, \
                mock.patch('six.moves.builtins.open'):
            mock_exists.return_value = True
            mock_isfile.return_value = True
            self.assertRaises(exceptions.DeploymentError,
                              self.cmd.take_action, parsed_args)


class TestOvercloudUpdateRun(fakes.TestOvercloudUpdateRun):

    def setUp(self):
        super(TestOvercloudUpdateRun, self).setUp()

        # Get the command object to test
        app_args = mock.Mock()
        app_args.verbose_level = 1
        self.cmd = overcloud_update.UpdateRun(self.app, app_args)

        uuid4_patcher = mock.patch('uuid.uuid4', return_value="UUID4")
        self.mock_uuid4 = uuid4_patcher.start()
        self.addCleanup(self.mock_uuid4.stop)

    @mock.patch('tripleoclient.utils.get_tripleo_ansible_inventory',
                return_value='/home/fake/inventory.yaml')
    @mock.patch('tripleoclient.utils.prompt_user_for_confirmation',
                return_value=True)
    @mock.patch('tripleoclient.workflows.package_update.update_ansible',
                autospec=True)
    @mock.patch('os.path.expanduser')
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_update_with_playbook_and_user(self, mock_execute,
                                           mock_expanduser, update_ansible,
                                           mock_confirm, mock_inventory):
        mock_expanduser.return_value = '/home/fake/'
        argslist = ['--limit', 'Compute',
                    '--playbook', 'fake-playbook.yaml',
                    '--ssh-user', 'tripleo-admin']
        verifylist = [
            ('limit', 'Compute'),
            ('static_inventory', None),
            ('playbook', 'fake-playbook.yaml'),
            ('ssh_user', 'tripleo-admin')
        ]

        parsed_args = self.check_parser(self.cmd, argslist, verifylist)
        with mock.patch('os.path.exists') as mock_exists:
            mock_exists.return_value = True
            self.cmd.take_action(parsed_args)
            update_ansible.assert_called_once_with(
                self.app.client_manager,
                container='overcloud',
                nodes='Compute',
                inventory_file=mock_inventory.return_value,
                playbook='fake-playbook.yaml',
                node_user='tripleo-admin',
                tags=None,
                skip_tags=None,
                verbosity=1,
                extra_vars=None
            )

    @mock.patch('tripleoclient.utils.get_tripleo_ansible_inventory',
                return_value='/home/fake/inventory.yaml')
    @mock.patch('tripleoclient.utils.prompt_user_for_confirmation',
                return_value=True)
    @mock.patch('tripleoclient.workflows.package_update.update_ansible',
                autospec=True)
    @mock.patch('os.path.expanduser')
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_update_limit_with_all_playbooks(self, mock_execute,
                                             mock_expanduser, update_ansible,
                                             mock_confirm, mock_inventory):
        mock_expanduser.return_value = '/home/fake/'
        argslist = ['--limit', 'Compute', '--playbook', 'all']
        verifylist = [
            ('limit', 'Compute'),
            ('static_inventory', None),
            ('playbook', 'all')
        ]

        parsed_args = self.check_parser(self.cmd, argslist, verifylist)
        with mock.patch('os.path.exists') as mock_exists:
            mock_exists.return_value = True
            self.cmd.take_action(parsed_args)
            for book in constants.MINOR_UPDATE_PLAYBOOKS:
                update_ansible.assert_any_call(
                    self.app.client_manager,
                    container='overcloud',
                    nodes='Compute',
                    inventory_file=mock_inventory.return_value,
                    playbook=book,
                    node_user='tripleo-admin',
                    tags=None,
                    skip_tags=None,
                    verbosity=1,
                    extra_vars=None
                )

    @mock.patch('tripleoclient.utils.prompt_user_for_confirmation',
                return_value=True)
    @mock.patch('tripleoclient.workflows.package_update.update_ansible',
                autospec=True)
    @mock.patch('os.path.expanduser')
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_update_with_no_limit(
            self, mock_execute, mock_expanduser, update_ansible,
            mock_confirm):
        mock_expanduser.return_value = '/home/fake/'
        argslist = []
        verifylist = [
            ('static_inventory', None),
            ('playbook', 'all')
        ]
        self.assertRaises(ParserException, lambda: self.check_parser(
            self.cmd, argslist, verifylist))


class TestOvercloudUpdateConverge(fakes.TestOvercloudUpdateConverge):

    def setUp(self):
        super(TestOvercloudUpdateConverge, self).setUp()

        # Get the command object to test
        app_args = mock.Mock()
        app_args.verbose_level = 1
        self.cmd = overcloud_update.UpdateConverge(self.app, app_args)

    @mock.patch('tripleoclient.utils.prompt_user_for_confirmation',
                return_value=True)
    @mock.patch(
        'tripleoclient.v1.overcloud_deploy.DeployOvercloud.take_action')
    def test_update_converge(self, deploy_action, mock_confirm):
        argslist = ['--templates', '--stack', 'cloud']
        verifylist = [
            ('stack', 'cloud')
        ]
        parsed_args = self.check_parser(self.cmd, argslist, verifylist)

        with mock.patch('os.path.exists') as mock_exists, \
                mock.patch('os.path.isfile') as mock_isfile:
            mock_exists.return_value = True
            mock_isfile.return_value = True
            self.cmd.take_action(parsed_args)
            assert('/usr/share/openstack-tripleo-heat-templates/'
                   'environments/lifecycle/update-converge.yaml'
                   in parsed_args.environment_files)
            deploy_action.assert_called_once_with(parsed_args)
