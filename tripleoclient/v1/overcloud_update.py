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

import logging
import os
import yaml

from heatclient.common import template_utils
from osc_lib.i18n import _
from oslo_concurrency import processutils

from tripleoclient import command
from tripleoclient import constants
from tripleoclient import exceptions
from tripleoclient import utils as oooutils
from tripleoclient.workflows import package_update


class UpdateOvercloud(command.Command):
    """Updates packages on overcloud nodes"""

    log = logging.getLogger(__name__ + ".UpdateOvercloud")

    def get_parser(self, prog_name):
        parser = super(UpdateOvercloud, self).get_parser(prog_name)
        parser.add_argument('--stack',
                            nargs='?',
                            dest='stack',
                            help=_('Name or ID of heat stack to scale '
                                   '(default=Env: OVERCLOUD_STACK_NAME)'),
                            default='overcloud'
                            )
        parser.add_argument('--templates',
                            nargs='?',
                            default=constants.TRIPLEO_HEAT_TEMPLATES,
                            help=_("The directory containing the Heat"
                                   "templates to deploy. "),
                            )
        parser.add_argument('--init-update',
                            dest='init_update',
                            action='store_true',
                            help=_("Run a heat stack update to generate the "
                                   "ansible playbooks."
                                   "Needs to be run only once"),
                            )
        parser.add_argument('--container-registry-file',
                            dest='container_registry_file',
                            default=None,
                            help=_("File which contains the container "
                                   "registry data for the update"),
                            )
        parser.add_argument('--ceph-ansible-playbook',
                            action="store",
                            default="/usr/share/ceph-ansible"
                                    "/site-docker.yml.sample",
                            help=_('Path to switch the ceph-ansible playbook '
                                   'used for update. This value should be set '
                                   'during the init-minor-update step.')
                            )
        parser.add_argument('--extra-environment', '-e',
                            action='append',
                            dest='environment_files',
                            default=[],
                            help=_("Extra environment required for the "
                                   "major update"),
                            )
        parser.add_argument('--nodes',
                            action="store",
                            default=None,
                            help=_("Nodes to update. If none and the "
                                   "--init-update set to false, it "
                                   "will run the update on all nodes.")
                            )
        parser.add_argument('--playbook',
                            action="store",
                            default="update_steps_playbook.yaml",
                            help=_("Playbook to use for update/upgrade.")
                            )
        parser.add_argument('--static-inventory',
                            dest='static_inventory',
                            action="store",
                            default=None,
                            help=_('Path to an existing ansible inventory to '
                                   'use. If not specified, one will be '
                                   'generated in '
                                   '~/tripleo-ansible-inventory.yaml')
                            )
        return parser

    def take_action(self, parsed_args):
        self.log.debug("take_action(%s)" % parsed_args)
        clients = self.app.client_manager

        stack = oooutils.get_stack(clients.orchestration,
                                   parsed_args.stack)

        stack_name = stack.stack_name
        container_registry = parsed_args.container_registry_file
        init_update = parsed_args.init_update

        if init_update:
            # Update the container registry:
            if container_registry:
                with open(os.path.abspath(container_registry)) as content:
                    registry = yaml.load(content.read())
            else:
                self.log.warning(
                    "You have not provided a container registry file. Note "
                    "that none of the containers on your environement will be "
                    "updated. If you want to update your container you have "
                    "to re-run this command and provide the registry file "
                    "with: --container-registry-file option.")
                registry = None
            # Extra env file
            environment_files = parsed_args.environment_files
            env = {}
            if environment_files:
                env_files, env = (
                    template_utils.process_multiple_environments_and_files(
                        env_paths=environment_files))
            # Run update
            ceph_ansible_playbook = parsed_args.ceph_ansible_playbook
            package_update.update(clients, container=stack_name,
                                  container_registry=registry,
                                  ceph_ansible_playbook=ceph_ansible_playbook,
                                  environments=env)
            package_update.get_config(clients, container=stack_name)
            print("Update init on stack {0} complete.".format(
                  parsed_args.stack))
        else:
            # Run ansible:
            nodes = parsed_args.nodes
            playbook = parsed_args.playbook
            inventory_file = parsed_args.static_inventory
            if inventory_file is None:
                inventory_file = '%s/%s' % (os.path.expanduser('~'),
                                            'tripleo-ansible-inventory.yaml')
                try:
                    processutils.execute(
                        '/usr/bin/tripleo-ansible-inventory',
                        '--static-yaml-inventory', inventory_file)
                except processutils.ProcessExecutionError as e:
                    message = "Failed to generate inventory: %s" % str(e)
                    raise exceptions.InvalidConfiguration(message)
            if os.path.exists(inventory_file):
                inventory = open(inventory_file, 'r').read()
            else:
                raise exceptions.InvalidConfiguration(
                    "Inventory file %s can not be found." % inventory_file)
            package_update.update_ansible(
                clients, nodes=nodes,
                inventory_file=inventory,
                playbook=playbook,
                ansible_queue_name=constants.UPDATE_QUEUE)


class UpgradeOvercloud(UpdateOvercloud):
    """Upgrade Overcloud Nodes"""

    log = logging.getLogger(__name__ + ".UpgradeOvercloud")

    def get_parser(self, prog_name):
        parser = super(UpgradeOvercloud, self).get_parser(prog_name)
        parser.add_argument('--converge',
                            dest='converge',
                            action='store_true',
                            help=_("Upgrade converge step"),
                            )
        parser.add_argument('--upgrade-converge-environment-file',
                            dest='upgrade_converge_file',
                            default="%senvironments/%s" % (
                                constants.TRIPLEO_HEAT_TEMPLATES,
                                constants.UPGRADE_CONVERGE_FILE),
                            help=_("Upgrade environment file which perform "
                                   "the converge of the Overcloud"),
                            )
        return parser

    def take_action(self, parsed_args):
        self.log.debug("take_action(%s)" % parsed_args)
        clients = self.app.client_manager

        stack = oooutils.get_stack(clients.orchestration,
                                   parsed_args.stack)

        stack_name = stack.stack_name
        converge = parsed_args.converge

        if converge:
            converge_file = parsed_args.upgrade_converge_file
            # Add the converge file to the user environment:
            if converge_file:
                with open(os.path.abspath(converge_file)) as conv_content:
                    converge_env = yaml.load(conv_content.read())
            # Run converge steps
            package_update.converge_nodes(clients,
                                          converge_env=converge_env,
                                          container=stack_name)
        else:
            super(UpgradeOvercloud, self).take_action(parsed_args)
