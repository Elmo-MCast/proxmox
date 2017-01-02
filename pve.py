from fabric.api import *
import os

""" Configurations """

env.hosts = ['128.112.168.26']
env.user = 'root'
env.password = 'PrincetonP4OVS1'
env.warn_only = True
env["poweredge_name"] = 'mshahbaz-poweredge-1-pve'
# env['vm_ssh_key'] = '/root/ssh/id_rsa'
env['vm_ssh_passwd'] = 'nopass'


""" Basic PVE Commands"""


def ssh_run(vm_id, command, log_file=None):
    if not "vm_ssh_passwd" in env:
        abort("couldn't find 'vm_ssh_passwd' variable in env.")

    if log_file:
        return run("sshpass -p " + env['vm_ssh_passwd'] +
                   " ssh -o 'StrictHostKeyChecking no' mshahbaz@10.10.10.%s \"%s\" > %s" % (vm_id, command, log_file))
    else:
        return run("sshpass -p " + env['vm_ssh_passwd'] +
                   " ssh -o 'StrictHostKeyChecking no' mshahbaz@10.10.10.%s \"%s\"" % (vm_id, command))


def scp_get(vm_id, src, dst, log_file=None):
    if not "vm_ssh_passwd" in env:
        abort("couldn't find 'vm_ssh_passwd' variable in env.")

    if log_file:
        run("sshpass -p " + env['vm_ssh_passwd'] +
            " scp -o 'StrictHostKeyChecking no' mshahbaz@10.10.10.%s:%s %s > %s"
            % (vm_id, src, dst, log_file))
    else:
        run("sshpass -p " + env['vm_ssh_passwd'] +
            " scp -o 'StrictHostKeyChecking no' mshahbaz@10.10.10.%s:%s %s"
            % (vm_id, src, dst))


def clone_vm(base_vm_id, vm_id, vm_name, full=False):
    if not "poweredge_name" in env:
        abort("couldn't find 'poweredge_name' variable in env.")

    if full:
        run("pvesh create /nodes/"+env["poweredge_name"]+"/qemu/%s/clone -newid %s -name %s -full"
            % (base_vm_id, vm_id, vm_name))
    else:
        run("pvesh create /nodes/"+env["poweredge_name"]+"/qemu/%s/clone -newid %s -name %s"
            % (base_vm_id, vm_id, vm_name))


def start_vm(vm_id):
    if not "poweredge_name" in env:
        abort("couldn't find 'poweredge_name' variable in env.")

    run("pvesh create /nodes/"+env["poweredge_name"]+"/qemu/%s/status/start" % (vm_id,))


def start_vms(*vm_ids):
    for vm_id in vm_ids:
        start_vm(vm_id)


def stop_vm(vm_id):
    if not "poweredge_name" in env:
        abort("couldn't find 'poweredge_name' variable in env.")

    run("pvesh create /nodes/"+env["poweredge_name"]+"/qemu/%s/status/stop" % (vm_id,))


def stop_vms(*vm_ids):
    for vm_id in vm_ids:
        stop_vm(vm_id)


def delete_vm(vm_id):
    if not "poweredge_name" in env:
        abort("couldn't find 'poweredge_name' variable in env.")

    run("pvesh delete /nodes/"+env["poweredge_name"]+"/qemu/%s" % (vm_id,))


def delete_vms(*vm_ids):
    for vm_id in vm_ids:
        delete_vm(vm_id)


def reboot_vm(vm_id):
    stop_vm(vm_id)
    start_vm(vm_id)


def sync_vm(vm_id):
    ssh_run(vm_id, 'sync')


def is_vm_ready(vm_id):
    if not "vm_ssh_passwd" in env:
        abort("couldn't find 'vm_ssh_passwd' variable in env.")

    run("sshpass -p " + env['vm_ssh_passwd'] +
        " ssh -o 'StrictHostKeyChecking no' mshahbaz@10.10.10." + str(vm_id) + " 'date'; "
        "while test $? -gt 0; do "
        "  sleep 5; echo 'Trying again ...'; "
        "  " +
        "sshpass -p " + env['vm_ssh_passwd'] +
        " ssh -o 'StrictHostKeyChecking no' mshahbaz@10.10.10." + str(vm_id) + " 'date'; "
        "done")


# Note: using sshpass instead of ssh keys.
# def install_ssh_key_on_host(key_local_path):
#     if "vm_ssh_key" in env:
#         key_name = os.path.basename(env["vm_ssh_key"])
#         key_path = os.path.dirname(env["vm_ssh_key"])
#         run('mkdir -p ' + key_path)
#         put(key_local_path+"/" + key_name, key_path)
#         put(key_local_path + "/" + key_name + ".pub", key_path)
#         run("chmod 600 " + env["vm_ssh_key"])
#     else:
#         abort("couldn't find 'vm_ssh_key' variable in env.")


# def remove_ssh_key_on_host():
#     if "vm_ssh_key" in env:
#         key_path = os.path.dirname(env["vm_ssh_key"])
#         run('rm -rf ' + key_path)
#     else:
#         abort("couldn't find 'vm_ssh_key' variable in env.")


def configure_host():
    run('apt-get install sshpass')


def configure_vm_network(old_vm_id, vm_id):
    ssh_run(old_vm_id,
            "sudo sed -i 's/address 10.10.10.%s/address 10.10.10.%s/g' /etc/network/interfaces; "
            "sudo sed -i 's/ubuntu-14-%s/ubuntu-14-%s/g' /etc/hostname; "
            "sudo sed -i 's/10.10.10.%s/10.10.10.%s/g' /etc/hosts; "
            "sudo sed -i 's/ubuntu-14-%s/ubuntu-14-%s/g' /etc/hosts"
            % (old_vm_id, vm_id,
               old_vm_id, vm_id,
               old_vm_id, vm_id,
               old_vm_id, vm_id))


# Note: make sure that base VM is set with nopasswd for sudo.
# def configure_vm_sudo_nopasswd(vm_id):
#     ssh_run(vm_id,
#             "sudo sed -i 's/sudo\tALL=(ALL:ALL) ALL/sudo\tALL=(ALL:ALL) NOPASSWD:ALL/g' /etc/sudoers")


def generate_vm(base_vm_id, vm_id, vm_name, full=False):
    clone_vm(base_vm_id, vm_id, vm_name, full)
    start_vm(vm_id)
    is_vm_ready(base_vm_id)
    configure_vm_network(base_vm_id, vm_id)
    sync_vm(base_vm_id)
    reboot_vm(vm_id)
    is_vm_ready(vm_id)


def generate_vms(base_vm_id, prefix, *vm_ids):
    for vm_id in vm_ids:
        generate_vm(base_vm_id, vm_id, '%s-%s' % (prefix, vm_id))


def destroy_vm(vm_id):
    stop_vm(vm_id)
    delete_vm(vm_id)


def destroy_vms(*vm_ids):
    for vm_id in vm_ids:
        destroy_vm(vm_id)


def add_host(vm_id, host_vm_id, host_vm_name):
    ssh_run(vm_id, "echo '10.10.10.%s %s' | sudo tee -a /etc/hosts"
            % (host_vm_id, host_vm_name))


def add_route(vm_id, prefix, iface):
    ssh_run(vm_id,
            "sudo ip route add %s dev %s" % (prefix, iface))


def del_route(vm_id, prefix, iface):
    ssh_run(vm_id,
            "sudo ip route del %s dev %s" % (prefix, iface))