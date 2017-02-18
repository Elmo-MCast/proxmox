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
        return run("sshpass -p %s ssh -o StrictHostKeyChecking=no %s@%s%s \"%s\" > %s"
                   % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
                      vm_id, command, log_file))
    else:
        return run("sshpass -p %s ssh -o StrictHostKeyChecking=no %s@%s%s \"%s\""
                   % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
                      vm_id, command))


def local_parallel_run(commands, display_only=False):
    if isinstance(commands, list):
        script = "parallel :::"
        for command in commands:
            script += " \\\n"
            script += "'%s'" % (command.replace("'", "'\\''"))

        if display_only:
            print script
        else:
            local(script)
    else:
        abort("incorrect args (should be a list of commands")


def parallel_run(commands, display_only=False):
    if isinstance(commands, list):
        script = "parallel :::"
        for command in commands:
            script += " \\\n"
            script += "'%s'" % (command.replace("'", "'\\''"))

        if display_only:
            print script
        else:
            run(script)
    else:
        abort("incorrect args (should be a dict of vm_id/command pair)")


def vm_parallel_run(commands, display_only=False):
    if isinstance(commands, dict):
        script = "parallel :::"
        for vm_id in commands:
            if isinstance(commands[vm_id], list):
                for command in commands[vm_id]:
                    script += " \\\n"
                    script += "'sshpass -p %s ssh -o StrictHostKeyChecking=no %s@%s%s \"%s\"'" \
                              % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
                                 vm_id, command.replace("'", "'\\''"))
            else:
                script += " \\\n"
                script += "'sshpass -p %s ssh -o StrictHostKeyChecking=no %s@%s%s \"%s\"'" \
                          % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
                             vm_id, commands[vm_id].replace("'", "'\\''"))

        if display_only:
            print script
        else:
            run(script)
    else:
        abort("incorrect args (should be a dict of vm_id/list of commands pair)")


def vm_get(vm_id, src, dst, log_file=None):
    if log_file:
        run("sshpass -p %s scp -o StrictHostKeyChecking=no %s@%s%s:%s %s > %s"
            % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
               vm_id, src, dst, log_file))
    else:
        run("sshpass -p %s scp -o StrictHostKeyChecking=no %s@%s%s:%s %s"
            % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
               vm_id, src, dst))


def parallel_get(commands, display_only=False):
    if isinstance(commands, list):
        script = "parallel :::"
        for command in commands:
            script += " \\\n"
            script += "'sshpass -p %s scp -o StrictHostKeyChecking=no %s:%s %s'" \
                      % (env.password, env.host_string, command['src'], command['dst'])

        if display_only:
            print script
        else:
            local(script)
    else:
        abort("incorrect args (should be a dict of vm_id/{src,dst} pair)")


def vm_parallel_get(commands, display_only=False):
    if isinstance(commands, dict):
        script = "parallel :::"
        for vm_id in commands:
            if isinstance(commands[vm_id], list):
                for command in commands[vm_id]:
                    script += " \\\n"
                    script += "'sshpass -p %s scp -o StrictHostKeyChecking=no %s@%s%s:%s %s'" \
                              % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
                                 vm_id, command['src'], command['dst'])
            else:
                script += " \\\n"
                script += "'sshpass -p %s scp -o StrictHostKeyChecking=no %s@%s%s:%s %s'" \
                          % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'],
                             vm_id, commands[vm_id]['src'], commands[vm_id]['dst'])

        if display_only:
            print script
        else:
            run(script)
    else:
        abort("incorrect args (should be a dict of vm_id/[{src,dst}] pair)")


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


def vm_stop(vm_id):
    run("pvesh create /nodes/%s/qemu/%s/status/stop"
        % (run("hostname"), vm_id))


def vm_reboot(vm_id):
    vm_run(vm_id, "sync; sudo reboot; ")


def vm_parallel_reboot(vm_ids):
    vm_parallel_run({vm_id: "sync; sudo reboot; " for vm_id in vm_ids})


def vm_delete(vm_id):
    run("pvesh delete /nodes/%s/qemu/%s"
        % (run("hostname"), vm_id))


def vm_is_ready(vm_id):
    run("sshpass -p %s ssh -o StrictHostKeyChecking=no %s@%s%s 'date'; "
        "while test $? -gt 0; do "
        "  sleep 5; echo 'Trying again ...'; "
        "  sshpass -p %s ssh -o StrictHostKeyChecking=no %s@%s%s 'date'; "
        "done"
        % (env['vm']['password'], env['vm']['user'], env['vm']['prefix'], str(vm_id),
           env['vm']['password'], env['vm']['user'], env['vm']['prefix'], str(vm_id)))


def configure():
    run('apt-get -y install sshpass parallel')


def vm_configure_sudo_pwdless(vm_id):
    vm_run(vm_id,
           "echo %s | "
           "sudo -S sed -i 's/sudo\\\tALL=(ALL:ALL) ALL/sudo\\\tALL=(ALL:ALL) NOPASSWD:ALL/g' /etc/sudoers"
           % (env['vm']['password'],))


def vm_configure(base_vm_id, vm_id):
    vm_run(base_vm_id,
           "sudo sed -i 's/address %s%s/address %s%s/g' /etc/network/interfaces; "
           "sudo sed -i 's/ubuntu-14-%s/ubuntu-14-%s/g' /etc/hostname; "
           "sudo sed -i 's/%s%s/%s%s/g' /etc/hosts; "
           "sudo sed -i 's/ubuntu-14-%s/ubuntu-14-%s/g' /etc/hosts; "
           % (env['vm']['prefix'], base_vm_id, env['vm']['prefix'], vm_id,
              base_vm_id, vm_id,
              env['vm']['prefix'], base_vm_id, env['vm']['prefix'], vm_id,
              base_vm_id, vm_id))


def vm_generate(base_vm_id, vm_id, vm_name, full=False, command_scripts=None):
    vm_clone(base_vm_id, vm_id, vm_name, full)
    vm_start(vm_id)
    vm_is_ready(base_vm_id)
    vm_configure_sudo_pwdless(base_vm_id)  # Note: this is necessary for running ssh commands on the VM
    vm_configure(base_vm_id, vm_id)
    vm_reboot(base_vm_id)
    vm_is_ready(vm_id)

    if command_scripts:
        for command_script in command_scripts:
            vm_run(vm_id, command_script)
        vm_reboot(vm_id)
        vm_is_ready(vm_id)


def vm_generate_multi(base_vm_id, prefix, full=False, command_scripts=None, *vm_ids):
    for vm_id in vm_ids:
        vm_generate(base_vm_id, vm_id, '%s-%s' % (prefix, vm_id), full)

    if command_scripts:
        for command_script in command_scripts:
            scripts = dict()
            for vm_id in vm_ids:
                scripts[vm_id] = command_script
            vm_parallel_run(scripts)
        vm_parallel_reboot(vm_ids)
        for vm_id in vm_ids:
            vm_is_ready(vm_id)


def vm_destroy(vm_id):
    vm_stop(vm_id)
    vm_delete(vm_id)


def vm_destroy_multi(*vm_ids):
    for vm_id in vm_ids:
        vm_destroy(vm_id)


def vm_options(vm_id, option, value):
    "Current options are: sockets, cores, memory"
    run("pvesh set /nodes/%s/qemu/%s/config -%s %s"
        % (run("hostname"), vm_id, option, value))


def vm_options_multi(option, value, *vm_ids):
    for vm_id in vm_ids:
        vm_options(vm_id, option, value)


# def vm_add_host(vm_id, host_vm_id, host_vm_name):
#     vm_run(vm_id, "echo '%s%s %s' | sudo tee -a /etc/hosts"
#            % (env['vm']['prefix'], host_vm_id, host_vm_name))


# def vm_add_route(vm_id, prefix, iface):
#     vm_run(vm_id,
#             "sudo ip route add %s dev %s" % (prefix, iface))


# def vm_del_route(vm_id, prefix, iface):
#     vm_run(vm_id,
#             "sudo ip route del %s dev %s" % (prefix, iface))
