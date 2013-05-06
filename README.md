To get going, you need fabric and libcloud installed, and to setup your config.py:

* Install depedencies:

        pip -r requirements.txt

* Setup config.py

        cp dist/config.py .

* Then edit config.py to add your AWS access keys, account number, and certificate locations.

To provision on EC2:

* First you need to boot a node that can build the image. The easiest way is to use the AWS console and boot an Ubuntu 12.04 instance. 

        fab -H ec2-instance-dns-name.compute-1.amazonaws.com build_ami:http://location/of/coreos.bin.gz

* When that script finishes, copy the ami-id that prints out and then run:

        fab create_node:test-name:ami-id

* As a helper, you can run this to check the console output of the node:

        fab -H ec2-instance-dns-name.compute-1.amazonaws.com console:i-instanceid
