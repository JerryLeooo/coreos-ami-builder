from fabric.api import run, put, env, execute, cd, sudo, settings

from fabric.operations import open_shell

from fabric.contrib.files import exists

from config import config
import time
#env.password = config['host_pass']
env.user = 'ubuntu'
env.key_filename = 'dist/key.pem'

def setup_host():
  sudo('echo deb http://us-east-1.ec2.archive.ubuntu.com/ubuntu/ precise multiverse >> /etc/apt/sources.list')
  sudo('echo deb http://us-east-1.ec2.archive.ubuntu.com/ubuntu/ precise-updates multiverse >> /etc/apt/sources.list')
  sudo('apt-get update')
  sudo('apt-get -y install ec2-api-tools ec2-ami-tools gdisk')

def run_all():
  _set_or_create_build_host()
  execute(setup_host)

def build_ami(image_loc, ebs=None):
  fetch_image(image_loc)
  #setup_grub()
  burn_image(ebs)
  make_ami()

def copy_image(image_loc):
  sudo('cp %s /tmp/coreos.bin' % (image_loc))
  
def fetch_image(image_loc):
  run('curl %s | gunzip > /tmp/coreos.bin' % (image_loc))

def burn_to_ebs(ebs):
  sudo('dd if=/tmp/coreos.bin of=%s bs=128M' % (ebs))

def burn_image():
  # convert to MBR
  sudo("""gdisk /tmp/coreos.bin <<EOF
r
h
1
N
EF
Y
N
w
Y
EOF""")
  # set boot flag, change partition types to linux
  sudo("""fdisk /tmp/coreos.bin <<EOF
t
1
e
w
EOF""")

def setup_grub():
  sudo('mkdir -p /mnt/stateful')
  offset = run('fdisk -l -u /tmp/coreos.bin|grep bin1|awk \'{print $3}\'')
  offset = int(offset)*512
  sudo('mount -o loop,offset=%s /tmp/coreos.bin /mnt/stateful' % (offset))
  sudo('mkdir -p /mnt/stateful/boot/grub')
  put('files/boot/grub/menu.lst', '/mnt/stateful/boot/grub/menu.lst', use_sudo=True)
  sudo('umount /mnt/stateful')
  sudo('rm -r /mnt/stateful')

def make_ami(img='coreos.bin'):
  put(config['aws_pk'], '/tmp/aws-pk.pem')
  put(config['aws_cert'], '/tmp/aws-cert.pem')
  run('ec2-bundle-image -k /tmp/aws-pk.pem -c /tmp/aws-cert.pem -u %s -i /tmp/%s -r x86_64 --kernel aki-b4aa75dd' % (config['aws_user_id'], img))
  run('ec2-upload-bundle -b coreos-images -m /tmp/%s.manifest.xml -a %s -s %s' % (img, config['aws_access_key'], config['aws_secret_key']))
  out = run('ec2-register coreos-images/%s.manifest.xml -K %s -C %s --root-device-name=/dev/sda' % (img, '/tmp/aws-pk.pem', '/tmp/aws-cert.pem'))
  ami = out.split('\t')[1]
  create_and_console(ami)

def make_ami_from_snap(snap):
  put(config['aws_pk'], '/tmp/aws-pk.pem')
  put(config['aws_cert'], '/tmp/aws-cert.pem')
  run('ec2-register -b "/dev/sda=%s::false" -b "/dev/sdb=ephemeral0" -n "CoreOS %s" -d "CoreOS latest" -a x86_64 --kernel aki-b4aa75dd -K %s -C %s' % (snap, int(time.time()), '/tmp/aws-pk.pem', '/tmp/aws-cert.pem'))

# grabs the console data from the EC2 api
def console(instance_id):
  with settings(warn_only=True):
    while True:
      run('ec2-get-console-output -K %s -C %s %s' % ('/tmp/aws-pk.pem', '/tmp/aws-cert.pem', instance_id))
      time.sleep(2)

# helper to ssh to a host by name
def ssh(name):
  _set_hosts_by_name(name)
  execute(open_shell)

# libcloud helper to setup libcloud driver
def _get_aws_driver():
  import libcloud.compute.providers
  import libcloud.security
  libcloud.security.CA_CERTS_PATH.append('dist/cacert.pem')
  CompEC2 = libcloud.compute.providers.get_driver(libcloud.compute.types.Provider.EC2_US_EAST)
  compdriver = CompEC2(config['aws_access_key'], config['aws_secret_key'])
  return compdriver

# fabric helper, will setup env.hosts using the given libcloud node
def _set_hosts_by_node(node):
  import socket
  for ip in node.public_ips:
    try:
      socket.inet_aton(ip)
      env.hosts = [str(ip)]
    except socket.error:
      pass

def _set_or_create_build_host():
  driver = _get_aws_driver()
  name = 'build-host'
  nodes = [x for x in driver.list_nodes() if x.name == name]
  if not nodes:
    create_build_host()
    nodes = [x for x in driver.list_nodes() if x.name == name]
  _set_hosts_by_node(nodes[0])

def _set_hosts_by_name(name):
  driver = _get_aws_driver()
  nodes = [x for x in driver.list_nodes() if x.name == name]
  _set_hosts_by_node(nodes[0])

def create_build_host(size='m1.small', ami='ami-3fec7956'):
  driver = _get_aws_driver()
  node = create_node(name='build-host', ami_id='ami-3fec7956', keyname='coreos-test', size=size)
  print node


# libcloud specific functions
def create_node(name, ami_id, keyname='coreos-test', security_group='quicklaunch-1', size='m1.small'):
  driver = _get_aws_driver()
  image = driver.list_images(ex_image_ids=[ami_id])[0]
  sizes = driver.list_sizes()
  size = [s for s in sizes if s.id == size][0]
  node = driver.create_node(name=name, size=size, image=image, ex_keyname=keyname, ex_securitygroup=security_group)
  nodes = driver.wait_until_running(nodes=[node])
  return nodes[0][0]

def show_node(name):
  driver = _get_rack_driver()
  nodes = [x for x in driver.list_nodes() if x.name == name]
  if len(nodes) != 1:
    raise 'Node %s not found' % (name)
  print nodes[0]

def destroy_node(name):
  driver = _get_aws_driver()
  nodes = [x for x in driver.list_nodes() if x.name == name and x.state == 0]
  if len(nodes) != 1:
    raise 'Node %s not found' % (name)
  node = nodes[0]
  driver.destroy_node(node)

def create_and_console(ami_id):
  node = create_node('auto', ami_id)
  console(node.id)
  
# build dummy images for AMI testing
def make_zero_img():
  run('dd if=/dev/zero of=/tmp/zero.img bs=50M count=1')
  run('mke2fs -F -j /tmp/zero.img')
  run('mkdir -p /mnt/zero')
  run('mount -o loop /tmp/zero.img /mnt/zero')

  run('mkdir -p /mnt/zero/boot/grub')
  put('files/boot/vmlinuz', '/mnt/zero/boot/vmlinuz')
  put('files/boot/grub/menu.lst', '/mnt/zero/boot/grub/menu.lst')
  run('umount /mnt/zero')
  run('rm -r /mnt/zero')

def make_zero_parted_img():
  run('dd if=/dev/zero of=/tmp/zero-parted.img bs=1 count=0 seek=256M')
  sudo('losetup /dev/loop0 /tmp/zero-parted.img')
  sudo('parted -s /dev/loop0 mklabel msdos')
  sudo('parted -s /dev/loop0 unit cyl mkpart primary fat32 -- 0 -2')
  sudo('parted -s /dev/loop0 toggle 1 boot')
  sudo('mkfs.vfat -I /dev/loop0p1')
  #sudo('mkfs.ext4 /dev/loop0p1')
  sudo('mkdir -p /mnt/zero')
  sudo('mount /dev/loop0p1 /mnt/zero')
  sudo('mkdir -p /mnt/zero/boot/grub')
  #put('files/boot/vmlinuz', '/mnt/zero/boot/vmlinuz', use_sudo=True)
  put('files/boot/grub/menu.lst', '/mnt/zero/boot/grub/menu.lst', use_sudo=True)
  cleanup_zero_parted_img()

def make_zero_parted_hybrid_img():
  run('dd if=/dev/zero of=/tmp/zero-parted.img bs=1 count=0 seek=256M')
  sudo('losetup /dev/loop0 /tmp/zero-parted.img')
  sudo('parted -s /dev/loop0 mklabel gpt')
  sudo('parted -s /dev/loop0 unit cyl mkpart primary fat32 -- 0 -2')
  sudo('parted -s /dev/loop0 toggle 1 boot')
  sudo('mkfs.vfat -I /dev/loop0p1')
  #sudo('mkfs.ext4 /dev/loop0p1')
  sudo('mkdir -p /mnt/zero')
  sudo('mount /dev/loop0p1 /mnt/zero')
  sudo('mkdir -p /mnt/zero/boot/grub')
  #put('files/boot/vmlinuz', '/mnt/zero/boot/vmlinuz', use_sudo=True)
  put('files/boot/grub/menu.lst', '/mnt/zero/boot/grub/menu.lst', use_sudo=True)
  cleanup_zero_parted_img()
  sudo("""gdisk /tmp/zero-parted.img <<EOF
r
h
1
N
EF
Y
N
w
Y
EOF""")
  # fdisk to change thing: t 1 e w

def cleanup_zero_parted_img():
  sudo('umount /mnt/zero')
  sudo('rm -r /mnt/zero')
  sudo('losetup -d /dev/loop0')
