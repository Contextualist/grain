#!/bin/bash
#PBS -l nodes=2:ppn=16,walltime=00:00:10:00
#PBS -l vmem=60gb
#PBS -N grain_example
#PBS -j oe
#PBS -o grain_example.log

######  Module commands #####

# Load module for the head node

cd $PBS_O_WORKDIR


######  Job commands go below this line #####

# Setup for the head node

sshq=(ssh -f -q -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null) # To ssh into worker nodes silently and in background
workers=$(cat $PBS_NODEFILE | uniq | tail -n+2)
date
while read -r node; do
    echo "going into $node"
    #                   vvvv---use your login shell to load your global settings
    "${sshq[@]}" $node "bash --login -c '
# Setup for a worker node (e.g. envar, modules, etc.)
# Invoke the worker
cd $PBS_O_WORKDIR
python -m grain.worker
'"
done <<< "$workers"
echo "$workers" | python YOUR_ENTRYPOINT.py # Invoke the head, passing in the worker addr (one per line)
date

# Cleanup for the job
