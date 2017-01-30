import os
import json
from fabric.api import *

""" Configurations """

with open(os.path.dirname(__file__) + "/pve.json") as json_file:
    settings = json.load(json_file)

env.warn_only = settings['env']['warn_only']
env.hosts = settings['env']['hosts']
env.user = settings['env']['user']
env.password = settings['env']['password']
env['vm'] = settings['env']['vm']


""" Basic PVE Commands"""


def vm_run(vm_id, command, log_file=None):
    if log_file:
        return run("sshpass -p %s ssh -o 'StrictHostKeyChecking no' %s@%s%s \"%s\" > %s"
                   % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
                      vm_id, command, log_file))
    else:
        return run("sshpass -p %s ssh -o 'StrictHostKeyChecking no' %s@%s%s \"%s\""
                   % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
                      vm_id, command))


def vm_parallel_run(commands):
    if isinstance(commands, dict):
        script = "parallel :::"
        for vm_id in commands:
            script += " \\\n"
            script += "'sshpass -p %s ssh %s@%s%s \"%s\"'" \
                          % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
                             vm_id, commands[vm_id].replace("'", "'\\''"))
        # print script
        run(script)
    else:
        abort("incorrect args (should be a dict of vm_id/command pair)")


def vm_get(vm_id, src, dst, log_file=None):
    if log_file:
        run("sshpass -p %s scp -o 'StrictHostKeyChecking no' %s@%s%s:%s %s > %s"
            % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
               vm_id, src, dst, log_file))
    else:
        run("sshpass -p %s scp -o 'StrictHostKeyChecking no' %s@%s%s:%s %s"
            % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
               vm_id, src, dst))


def vm_clone(base_vm_id, vm_id, vm_name, full=False):
    if full:
        run("pvesh create /nodes/%s/qemu/%s/clone -newid %s -name %s -full"
            % (run("hostname"), base_vm_id, vm_id, vm_name))
    else:
        run("pvesh create /nodes/%s/qemu/%s/clone -newid %s -name %s"
            % (run("hostname"), base_vm_id, vm_id, vm_name))


def vm_start(vm_id):
    run("pvesh create /nodes/%s/qemu/%s/status/start"
        % (run("hostname"), vm_id))


def vm_start_multi(*vm_ids):
    for vm_id in vm_ids:
        vm_start(vm_id)


def vm_stop(vm_id):
    run("pvesh create /nodes/%s/qemu/%s/status/stop"
        % (run("hostname"), vm_id))


def vm_stop_multi(*vm_ids):
    for vm_id in vm_ids:
        vm_stop(vm_id)


def vm_delete(vm_id):
    run("pvesh delete /nodes/%s/qemu/%s"
        % (run("hostname"), vm_id))


def vm_delete_multi(*vm_ids):
    for vm_id in vm_ids:
        vm_delete(vm_id)


def vm_reboot(vm_id):
    vm_stop(vm_id)
    vm_start(vm_id)


def vm_sync(vm_id):
    vm_run(vm_id, 'sync')


def vm_is_ready(vm_id):
    run("sshpass -p %s ssh -o 'StrictHostKeyChecking no' %s@%s%s 'date'; "
        "while test $? -gt 0; do "
        "  sleep 5; echo 'Trying again ...'; "
        "  sshpass -p %s ssh -o 'StrictHostKeyChecking no' %s@%s%s 'date'; "
        "done"
        % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'], str(vm_id),
           env['vm']['password'], env['vm']['user'], env['vm']['prefix'], str(vm_id)))


# Note: using sshpass instead of ssh keys.
# def install_ssh_key_on_host(key_local_path):
#     if "vm_ssh_key" in env:
#         key_name = os.path.basename(env["vm_ssh_key"])
#         key_path = os.path.dirname(env["vm_ssh_key"])
#         start('mkdir -p ' + key_path)
#         put(key_local_path+"/" + key_name, key_path)
#         put(key_local_path + "/" + key_name + ".pub", key_path)
#         start("chmod 600 " + env["vm_ssh_key"])
#     else:
#         abort("couldn't find 'vm_ssh_key' variable in env.")


# def remove_ssh_key_on_host():
#     if "vm_ssh_key" in env:
#         key_path = os.path.dirname(env["vm_ssh_key"])
#         start('rm -rf ' + key_path)
#     else:
#         abort("couldn't find 'vm_ssh_key' variable in env.")


def host_configure():
    run('apt-get install sshpass parallel')


def vm_configure_network(old_vm_id, vm_id):
    vm_run(old_vm_id,
            "sudo sed -i 's/address %s%s/address %s%s/g' /etc/network/interfaces; "
            "sudo sed -i 's/ubuntu-14-%s/ubuntu-14-%s/g' /etc/hostname; "
            "sudo sed -i 's/%s%s/%s%s/g' /etc/hosts; "
            "sudo sed -i 's/ubuntu-14-%s/ubuntu-14-%s/g' /etc/hosts"
           % (env['vm']['prefix'], old_vm_id, env['vm']['prefix'], vm_id,
               old_vm_id, vm_id,
               env['vm']['prefix'], old_vm_id, env['vm']['prefix'], vm_id,
               old_vm_id, vm_id))


# Note: make sure that base VM is set with nopasswd for sudo.
# def configure_vm_sudo_nopasswd(vm_id):
#     vm_run(vm_id,
#             "sudo sed -i 's/sudo\tALL=(ALL:ALL) ALL/sudo\tALL=(ALL:ALL) NOPASSWD:ALL/g' /etc/sudoers")


def vm_generate(base_vm_id, vm_id, vm_name, full=False):
    vm_clone(base_vm_id, vm_id, vm_name, full)
    vm_start(vm_id)
    vm_is_ready(base_vm_id)
    vm_configure_network(base_vm_id, vm_id)
    vm_sync(base_vm_id)
    vm_reboot(vm_id)
    vm_is_ready(vm_id)


def vm_generate_multi(base_vm_id, prefix, *vm_ids):
    for vm_id in vm_ids:
        vm_generate(base_vm_id, vm_id, '%s-%s' % (prefix, vm_id))


def vm_destroy(vm_id):
    vm_stop(vm_id)
    vm_delete(vm_id)


def vm_destroy_multi(*vm_ids):
    for vm_id in vm_ids:
        vm_destroy(vm_id)


def vm_add_host(vm_id, host_vm_id, host_vm_name):
    vm_run(vm_id, "echo '%s%s %s' | sudo tee -a /etc/hosts"
           % (env['vm']['prefix'], host_vm_id, host_vm_name))


def vm_add_route(vm_id, prefix, iface):
    vm_run(vm_id,
            "sudo ip route add %s dev %s" % (prefix, iface))


def vm_del_route(vm_id, prefix, iface):
    vm_run(vm_id,
            "sudo ip route del %s dev %s" % (prefix, iface))
