#   Copyright 2019 Red Hat, Inc.
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
import os

import mock
from unittest import TestCase

from tripleoclient import export


class TestExport(TestCase):
    def setUp(self):
        self.unlink_patch = mock.patch('os.unlink')
        self.addCleanup(self.unlink_patch.stop)
        self.unlink_patch.start()
        self.mock_log = mock.Mock('logging.getLogger')

        outputs = [
            {'output_key': 'EndpointMap',
             'output_value': dict(em_key='em_value')},
            {'output_key': 'HostsEntry',
             'output_value': 'hosts entry'},
            {'output_key': 'GlobalConfig',
             'output_value': dict(gc_key='gc_value')},
        ]
        self.mock_stack = mock.Mock()
        self.mock_stack.to_dict.return_value = dict(outputs=outputs)
        self.mock_open = mock.mock_open(read_data='{"an_key":"an_value"}')

        ceph_inv = {
            'DistributedComputeHCI': {
                'hosts': {
                    'dcn0-distributedcomputehci-0': {
                        'storage_ip': '192.168.24.42'
                    }
                }
            },
            'mons': {
                'children': {
                    'DistributedComputeHCI': {}
                }
            }
        }
        self.mock_open_ceph_inv = mock.mock_open(read_data=str(ceph_inv))

        ceph_all = {
            'cluster': 'dcn0',
            'fsid': 'a5a22d37-e01f-4fa0-a440-c72585c7487f',
            'keys': [
                {'name': 'client.openstack'}
            ]
        }
        self.mock_open_ceph_all = mock.mock_open(read_data=str(ceph_all))

    @mock.patch('tripleoclient.utils.get_stack')
    def test_export_stack(self, mock_get_stack):
        heat = mock.Mock()
        mock_get_stack.return_value = self.mock_stack
        with mock.patch('six.moves.builtins.open', self.mock_open):
            data = export.export_stack(heat, "overcloud")

        expected = \
            {'AllNodesExtraMapData': {u'an_key': u'an_value'},
             'EndpointMapOverride': {'em_key': 'em_value'},
             'ExtraHostFileEntries': 'hosts entry',
             'GlobalConfigExtraMapData': {'gc_key': 'gc_value'}}

        self.assertEqual(expected, data)
        self.mock_open.assert_called_once_with(
            os.path.join(
                os.environ.get('HOME'),
                'config-download/overcloud/group_vars/overcloud.json'),
            'r')

    @mock.patch('tripleoclient.utils.get_stack')
    def test_export_stack_should_filter(self, mock_get_stack):
        heat = mock.Mock()
        mock_get_stack.return_value = self.mock_stack
        self.mock_open = mock.mock_open(
            read_data='{"an_key":"an_value","ovn_dbs_vip":"vip"}')
        with mock.patch('six.moves.builtins.open', self.mock_open):
            data = export.export_stack(heat, "overcloud", should_filter=True)

        expected = \
            {'AllNodesExtraMapData': {u'ovn_dbs_vip': u'vip'},
             'EndpointMapOverride': {'em_key': 'em_value'},
             'ExtraHostFileEntries': 'hosts entry',
             'GlobalConfigExtraMapData': {'gc_key': 'gc_value'}}

        self.assertEqual(expected, data)
        self.mock_open.assert_called_once_with(
            os.path.join(
                os.environ.get('HOME'),
                'config-download/overcloud/group_vars/overcloud.json'),
            'r')

    @mock.patch('tripleoclient.utils.get_stack')
    def test_export_stack_cd_dir(self, mock_get_stack):
        heat = mock.Mock()
        mock_get_stack.return_value = self.mock_stack
        with mock.patch('six.moves.builtins.open', self.mock_open):
            export.export_stack(heat, "overcloud",
                                config_download_dir='/foo')
        self.mock_open.assert_called_once_with(
            '/foo/overcloud/group_vars/overcloud.json', 'r')

    @mock.patch('tripleoclient.utils.get_stack')
    def test_export_stack_stack_name(self, mock_get_stack):
        heat = mock.Mock()
        mock_get_stack.return_value = self.mock_stack
        with mock.patch('six.moves.builtins.open', self.mock_open):
            export.export_stack(heat, "control")
        mock_get_stack.assert_called_once_with(heat, 'control')

    @mock.patch('tripleo_common.utils.plan.generate_passwords')
    def test_export_passwords(self, mock_gen_pass):
        heat = mock.Mock()
        mock_passwords = {
            'AdminPassword': 'a_user',
            'RpcPassword': 'B'}
        mock_gen_pass.return_value = mock_passwords
        data = export.export_passwords(heat, 'overcloud')

        self.assertEqual(dict(AdminPassword='a_user',
                              RpcPassword='B'),
                         data)

    @mock.patch('tripleo_common.utils.plan.generate_passwords')
    def test_export_passwords_excludes(self, mock_gen_pass):
        heat = mock.Mock()
        mock_passwords = {
            'AdminPassword': 'A',
            'RpcPassword': 'B',
            'CephClientKey': 'cephkey',
            'CephClusterFSID': 'cephkey',
            'CephRgwKey': 'cephkey'}
        mock_gen_pass.return_value = mock_passwords
        data = export.export_passwords(heat, 'overcloud')

        mock_passwords.pop('CephClientKey')
        mock_passwords.pop('CephClusterFSID')
        mock_passwords.pop('CephRgwKey')

        self.assertEqual(mock_passwords, data)

    def test_export_storage_ips(self):
        with mock.patch('six.moves.builtins.open', self.mock_open_ceph_inv):
            storage_ips = export.export_storage_ips('dcn0',
                                                    config_download_dir='/foo')
        self.assertEqual(storage_ips, ['192.168.24.42'])
        self.mock_open_ceph_inv.assert_called_once_with(
            '/foo/dcn0/ceph-ansible/inventory.yml', 'r')

    def test_export_ceph(self):
        expected = {
            'external_cluster_mon_ips': '192.168.24.42',
            'keys': [
                {'name': 'client.openstack'}
            ],
            'ceph_conf_overrides': {
                'client': {
                    'keyring': '/etc/ceph/dcn0.client.openstack.keyring'
                }
            },
            'cluster': 'dcn0',
            'fsid': 'a5a22d37-e01f-4fa0-a440-c72585c7487f',
            'dashboard_enabled': False
        }
        with mock.patch('six.moves.builtins.open', self.mock_open_ceph_all):
            data = export.export_ceph('dcn0', 'openstack',
                                      config_download_dir='/foo',
                                      mon_ips=['192.168.24.42'])
        self.assertEqual(data, expected)
        self.mock_open_ceph_all.assert_called_once_with(
            '/foo/dcn0/ceph-ansible/group_vars/all.yml', 'r')
