# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy
import getpass
import os
import yaml

from heatclient.common import event_utils
from heatclient import exc as heat_exc
from openstackclient import shell
from tripleo_common.utils import overcloudrc as rc_utils
from tripleo_common.utils.safe_import import git

from tripleoclient.constants import ANSIBLE_TRIPLEO_PLAYBOOKS
from tripleoclient.constants import CLOUD_HOME_DIR
from tripleoclient.constants import DEFAULT_WORK_DIR
from tripleoclient import exceptions
from tripleoclient import utils


_WORKFLOW_TIMEOUT = 360  # 6 * 60 seconds


def create_overcloudrc(stack, rc_params, no_proxy='',
                       output_dir=CLOUD_HOME_DIR):
    overcloudrcs = rc_utils._create_overcloudrc(
        stack, no_proxy,
        rc_params['password'],
        rc_params['region'])
    rcpath = os.path.join(output_dir, '%src' % stack.stack_name)
    with open(rcpath, 'w') as rcfile:
        rcfile.write(overcloudrcs['overcloudrc'])
    os.chmod(rcpath, 0o600)
    return os.path.abspath(rcpath)


def deploy_without_plan(clients, stack, stack_name, template,
                        files, env_files,
                        log):
    orchestration_client = clients.orchestration
    if stack is None:
        log.info("Performing Heat stack create")
        action = 'CREATE'
        marker = None
    else:
        log.info("Performing Heat stack update")
        # Make sure existing parameters for stack are reused
        # Find the last top-level event to use for the first marker
        events = event_utils.get_events(orchestration_client,
                                        stack_id=stack_name,
                                        event_args={'sort_dir': 'desc',
                                                    'limit': 1})
        marker = events[0].id if events else None
        action = 'UPDATE'

    set_deployment_status(stack_name,
                          status='DEPLOYING')
    stack_args = {
        'stack_name': stack_name,
        'template': template,
        'environment_files': env_files,
        'files': files}
    try:
        if stack:
            stack_args['existing'] = True
            orchestration_client.stacks.update(stack.id, **stack_args)
        else:
            stack = orchestration_client.stacks.create(**stack_args)

        print("Success.")
    except Exception:
        set_deployment_status(stack_name,
                              status='DEPLOY_FAILED')
        raise

    create_result = utils.wait_for_stack_ready(
        orchestration_client, stack_name, marker, action)
    if not create_result:
        shell.OpenStackShell().run(["stack", "failures", "list", stack_name])
        set_deployment_status(
            stack_name,
            status='DEPLOY_FAILED'
        )
        if stack is None:
            raise exceptions.DeploymentError("Heat Stack create failed.")
        else:
            raise exceptions.DeploymentError("Heat Stack update failed.")


def get_overcloud_hosts(stack, ssh_network):
    ips = []
    role_net_ip_map = utils.get_role_net_ip_map(stack)
    blacklisted_ips = utils.get_blacklisted_ip_addresses(stack)
    for net_ip_map in role_net_ip_map.values():
        # get a copy of the lists of ssh_network and ctlplane ips
        # as blacklisted_ips will only be the ctlplane ips, we need
        # both lists to determine which to actually blacklist
        net_ips = copy.copy(net_ip_map.get(ssh_network, []))
        ctlplane_ips = copy.copy(net_ip_map.get('ctlplane', []))

        blacklisted_ctlplane_ips = \
            [ip for ip in ctlplane_ips if ip in blacklisted_ips]

        # for each blacklisted ctlplane ip, remove the corresponding
        # ssh_network ip at that same index in the net_ips list
        for bcip in blacklisted_ctlplane_ips:
            index = ctlplane_ips.index(bcip)
            ctlplane_ips.pop(index)
            net_ips.pop(index)

        ips.extend(net_ips)

    return ips


def get_hosts_and_enable_ssh_admin(stack, overcloud_ssh_network,
                                   overcloud_ssh_user, overcloud_ssh_key,
                                   overcloud_ssh_port_timeout,
                                   verbosity=0):
    """Enable ssh admin access.

    Get a list of hosts from a given stack and enable admin ssh across all of
    them.

    :param stack: Stack data.
    :type stack: Object

    :param overcloud_ssh_network: Network id.
    :type overcloud_ssh_network: String

    :param overcloud_ssh_user: SSH access username.
    :type overcloud_ssh_user: String

    :param overcloud_ssh_key: SSH access key.
    :type overcloud_ssh_key: String

    :param overcloud_ssh_port_timeout: Ansible connection timeout in seconds
    :type overcloud_ssh_port_timeout: Int

    :param verbosity: Verbosity level
    :type verbosity: Integer
    """

    hosts = get_overcloud_hosts(stack, overcloud_ssh_network)
    if [host for host in hosts if host]:
        enable_ssh_admin(
            stack,
            hosts,
            overcloud_ssh_user,
            overcloud_ssh_key,
            overcloud_ssh_port_timeout,
            verbosity=verbosity
        )
    else:
        raise exceptions.DeploymentError(
            'Cannot find any hosts on "{}" in network "{}"'.format(
                stack.stack_name,
                overcloud_ssh_network
            )
        )


def enable_ssh_admin(stack, hosts, ssh_user, ssh_key, timeout,
                     verbosity=0):
    """Run enable ssh admin access playbook.

    :param stack: Stack data.
    :type stack: Object

    :param hosts: Machines to connect to.
    :type hosts: List

    :param ssh_user: SSH access username.
    :type ssh_user: String

    :param ssh_key: SSH access key.
    :type ssh_key: String

    :param timeout: Ansible connection timeout in seconds
    :type timeout: int

    :param verbosity: Verbosity level
    :type verbosity: Integer
    """

    print(
        'Enabling ssh admin (tripleo-admin) for hosts: {}.'
        '\nUsing ssh user "{}" for initial connection.'
        '\nUsing ssh key at "{}" for initial connection.'
        '\n\nStarting ssh admin enablement playbook'.format(
            hosts,
            ssh_user,
            ssh_key
        )
    )
    with utils.TempDirs() as tmp:
        utils.run_ansible_playbook(
            playbook='cli-enable-ssh-admin.yaml',
            inventory=','.join(hosts),
            workdir=tmp,
            playbook_dir=ANSIBLE_TRIPLEO_PLAYBOOKS,
            key=ssh_key,
            ssh_user=ssh_user,
            verbosity=verbosity,
            extra_vars={
                "ssh_user": ssh_user,
                "ssh_servers": hosts,
                'tripleo_cloud_name': stack.stack_name
            },
            ansible_timeout=timeout
        )
    print("Enabling ssh admin - COMPLETE.")


def config_download(log, clients, stack, ssh_network='ctlplane',
                    output_dir=None, override_ansible_cfg=None,
                    timeout=600, verbosity=0, deployment_options=None,
                    in_flight_validations=False,
                    ansible_playbook_name='deploy_steps_playbook.yaml',
                    limit_hosts=None, extra_vars=None, inventory_path=None,
                    ssh_user='tripleo-admin', tags=None, skip_tags=None,
                    deployment_timeout=None, forks=None):
    """Run config download.

    :param log: Logging object
    :type log: Object

    :param clients: openstack clients
    :type clients: Object

    :param stack: Heat Stack object
    :type stack: Object

    :param ssh_network: Network named used to access the overcloud.
    :type ssh_network: String

    :param output_dir: Path to the output directory.
    :type output_dir: String

    :param override_ansible_cfg: Ansible configuration file location.
    :type override_ansible_cfg: String

    :param timeout: Ansible connection timeout in seconds.
    :type timeout: Integer

    :param verbosity: Ansible verbosity level.
    :type verbosity: Integer

    :param deployment_options: Additional deployment options.
    :type deployment_options: Dictionary

    :param in_flight_validations: Enable or Disable inflight validations.
    :type in_flight_validations: Boolean

    :param ansible_playbook_name: Name of the playbook to execute.
    :type ansible_playbook_name: String

    :param limit_hosts: String of hosts to limit the current playbook to.
    :type limit_hosts: String

    :param extra_vars: Set additional variables as a Dict or the absolute
                       path of a JSON or YAML file type.
    :type extra_vars: Either a Dict or the absolute path of JSON or YAML

    :param inventory_path: Inventory file or path, if None is provided this
                           function will perform a lookup
    :type inventory_path: String

    :param ssh_user: SSH user, defaults to tripleo-admin.
    :type ssh_user: String

    :param tags: Ansible inclusion tags.
    :type tags: String

    :param skip_tags: Ansible exclusion tags.
    :type skip_tags: String

    :param deployment_timeout: Deployment timeout in minutes.
    :type deployment_timeout: Integer

    """

    def _log_and_print(message, logger, level='info', print_msg=True):
        """Print and log a given message.

        :param message: Message to print and log.
        :type message: String

        :param log: Logging object
        :type log: Object

        :param level: Log level.
        :type level: String

        :param print_msg: Print messages to stdout.
        :type print_msg: Boolean
        """

        if print_msg:
            print(message)

        log = getattr(logger, level)
        log(message)

    if not output_dir:
        output_dir = DEFAULT_WORK_DIR

    if not deployment_options:
        deployment_options = dict()

    if not in_flight_validations:
        if skip_tags:
            skip_tags = 'opendev-validation,{}'.format(skip_tags)
        else:
            skip_tags = 'opendev-validation'

    with utils.TempDirs() as tmp:
        utils.run_ansible_playbook(
            playbook='cli-grant-local-access.yaml',
            inventory='localhost,',
            workdir=tmp,
            playbook_dir=ANSIBLE_TRIPLEO_PLAYBOOKS,
            verbosity=verbosity,
            extra_vars={
                'access_path': output_dir,
                'execution_user': getpass.getuser()
            }
        )

    _log_and_print(
        message='Checking for blacklisted hosts from stack: {}'.format(
            stack.stack_name
        ),
        logger=log,
        print_msg=(verbosity == 0)
    )
    if not limit_hosts:
        blacklist_show = stack.output_show('BlacklistedHostnames')
        blacklist_stack_output = blacklist_show.get('output', dict())
        blacklist_stack_output_value = blacklist_stack_output.get(
            'output_value')
        if blacklist_stack_output_value:
            limit_hosts = (
                ':'.join(['!{}'.format(i) for i in blacklist_stack_output_value
                          if i]))

    key_file = utils.get_key(stack.stack_name)
    python_interpreter = deployment_options.get('ansible_python_interpreter')

    with utils.TempDirs() as tmp:
        utils.run_ansible_playbook(
            playbook='cli-config-download.yaml',
            inventory='localhost,',
            workdir=tmp,
            playbook_dir=ANSIBLE_TRIPLEO_PLAYBOOKS,
            verbosity=verbosity,
            extra_vars={
                'plan': stack.stack_name,
                'output_dir': output_dir,
                'ansible_ssh_user': ssh_user,
                'ansible_ssh_private_key_file': key_file,
                'ssh_network': ssh_network,
                'python_interpreter': python_interpreter,
                'inventory_path': inventory_path
            }
        )

    _log_and_print(
        message='Executing deployment playbook for stack: {}'.format(
            stack.stack_name
        ),
        logger=log,
        print_msg=(verbosity == 0)
    )

    stack_work_dir = os.path.join(output_dir, stack.stack_name)
    if not inventory_path:
        inventory_path = os.path.join(stack_work_dir,
                                      'tripleo-ansible-inventory.yaml')

    if isinstance(ansible_playbook_name, list):
        playbooks = [os.path.join(stack_work_dir, p)
                     for p in ansible_playbook_name]
    else:
        playbooks = os.path.join(stack_work_dir, ansible_playbook_name)

    with utils.TempDirs() as tmp:
        utils.run_ansible_playbook(
            playbook=playbooks,
            inventory=inventory_path,
            workdir=tmp,
            playbook_dir=stack_work_dir,
            skip_tags=skip_tags,
            tags=tags,
            ansible_cfg=override_ansible_cfg,
            verbosity=verbosity,
            ssh_user=ssh_user,
            key=key_file,
            limit_hosts=limit_hosts,
            ansible_timeout=timeout,
            reproduce_command=True,
            extra_env_variables={
                'ANSIBLE_BECOME': True,
            },
            extra_vars=extra_vars,
            timeout=deployment_timeout,
            forks=forks
        )

    _log_and_print(
        message='Overcloud configuration completed for stack: {}'.format(
            stack.stack_name
        ),
        logger=log,
        print_msg=(verbosity == 0)
    )

    if os.path.exists(stack_work_dir):
        # Object to the git repository
        repo = git.Repo(stack_work_dir)

        # Configure git user.name and user.email
        git_config_user = "mistral"
        git_config_email = git_config_user + '@' + os.uname().nodename.strip()
        repo.config_writer().set_value(
            "user", "name", git_config_user
        ).release()
        repo.config_writer().set_value(
            "user", "email", git_config_email
        ).release()

        # Add and commit all files to the git repository
        repo.git.add(".")
        repo.git.commit("--amend", "--no-edit")


def get_horizon_url(stack, verbosity=0):
    """Return horizon URL string.

    :params stack: Stack name
    :type stack: string
    :returns: string
    """

    with utils.TempDirs() as tmp:
        horizon_tmp_file = os.path.join(tmp, 'horizon_url')
        utils.run_ansible_playbook(
            playbook='cli-undercloud-get-horizon-url.yaml',
            inventory='localhost,',
            workdir=tmp,
            playbook_dir=ANSIBLE_TRIPLEO_PLAYBOOKS,
            verbosity=verbosity,
            extra_vars={
                'stack_name': stack,
                'horizon_url_output_file': horizon_tmp_file
            }
        )

        with open(horizon_tmp_file) as f:
            return f.read().strip()


def get_deployment_status(clients, stack_name):
    """Return current deployment status."""

    try:
        clients.orchestration.stacks.get(stack_name)
    except heat_exc.HTTPNotFound:
        return None

    try:
        status_yaml = utils.get_status_yaml(stack_name)
        with open(status_yaml, 'r') as status_stream:
            return yaml.safe_load(status_stream)['deployment_status']
    except Exception:
        return None


def set_deployment_status(stack_name, status):
    utils.update_deployment_status(
        stack_name=stack_name,
        status=status)
