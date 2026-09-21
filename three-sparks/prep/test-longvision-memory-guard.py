#!/usr/bin/env python3
"""Mocked guard checks only: no Docker, SSH, remote reads or process signals."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

path=Path(__file__).with_name("longvision-memory-guard.py")
spec=importlib.util.spec_from_file_location("memory_guard",path)
guard=importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
CID="a"*64
NAME="glm53-longvision-c8-fair-v3"


def fixture():
    return {"Id":CID,"Name":"/"+NAME,"Image":guard.IMAGE,"Path":"python3",
        "Args":["-u","/work/longvision-c8.py","run","--prepared","/data/prepared"],
        "HostConfig":{"DeviceRequests":None,"Devices":[],"Privileged":False,"Runtime":"runc","RestartPolicy":{"Name":"no"}},
        "Mounts":[{"Source":"/home/ben/glm53-lab","Destination":"/data"}],"State":{"Running":True}}


class GuardTests(unittest.TestCase):
    def test_identity_gate_rejects_server_gpu_and_reused_name(self):
        good=fixture()
        self.assertEqual(guard.validate_container(good,NAME),CID)
        variants=[]
        for field,value in (("Name","/glm53-v2-r0"),("Image","sha256:"+"b"*64),("Path","bash"),
                            ("Args",["-m","vllm.entrypoints.openai.api_server"]),("Id","short")):
            bad=copy.deepcopy(good);bad[field]=value;variants.append(bad)
        for field,value in (("DeviceRequests",[{"Driver":"nvidia"}]),("Devices",[{"PathOnHost":"nvidia.com/gpu=all"}]),
                            ("Privileged",True),("Runtime","nvidia"),("RestartPolicy",{"Name":"always"})):
            bad=copy.deepcopy(good);bad["HostConfig"][field]=value;variants.append(bad)
        bad=copy.deepcopy(good);bad["Mounts"]=[{"Source":"/dev/nvidia0","Destination":"/dev/nvidia0"}];variants.append(bad)
        for item in variants:
            with self.assertRaises(ValueError): guard.validate_container(item,NAME)
        with self.assertRaises(ValueError): guard.validate_container(good,"glm53-v2-r0")

    def test_consecutive_low_failure_and_reset(self):
        state=guard.Consecutive()
        low=lambda:{"node":"head","mem_available_kib":guard.MIN_KIB-1}
        high=lambda:{"node":"head","mem_available_kib":guard.MIN_KIB}
        failure=lambda:{"node":"head","error_type":"TimeoutExpired"}
        self.assertFalse(state.update([low()]))
        self.assertFalse(state.update([high()]))
        self.assertFalse(state.update([low()]))
        self.assertEqual(state.update([low()])[0]["reason"],"two_consecutive_below_3GiB")
        self.assertFalse(state.update([failure()]))
        self.assertFalse(state.update([failure()]))
        self.assertEqual(state.update([failure()])[0]["reason"],"three_consecutive_read_failures")
        self.assertFalse(state.update([high()]))
        self.assertEqual(state.failed["head"],0)
        self.assertEqual(state.low["head"],0)

    def test_worker_read_commands_are_fixed_read_only(self):
        for node,(alias,address) in guard.WORKERS.items():
            command=guard.mem_command(node)
            self.assertEqual(command[:5],["runuser","-u","ben","--","ssh"])
            self.assertIn("HostKeyAlias="+alias,command)
            self.assertIn("ben@"+address,command)
            self.assertIn("BatchMode=yes",command)
            self.assertIn("StrictHostKeyChecking=yes",command)
            self.assertEqual(command[-1],guard.REMOTE_COMMAND)
            self.assertEqual(command[-1],"awk '/^MemAvailable:/ {print $2; found=1} END {if (!found) exit 2}' /proc/meminfo")

    def test_interrupt_and_escalation_only_address_validated_id(self):
        commands=[]; events=[]; tick=[0.0]
        def command(argv,timeout=8): commands.append(argv);return ""
        with mock.patch.object(guard,"command",side_effect=command), mock.patch.object(guard,"inspect",side_effect=[{"State":{"Running":True}},{"State":{"Running":False}}]):
            self.assertEqual(guard.stop_client(CID,events.append),"exited_after_interrupt")
        self.assertEqual(commands,[["docker","kill","--signal","INT",CID]])
        commands.clear()
        with mock.patch.object(guard,"command",side_effect=command), mock.patch.object(guard,"inspect",return_value={"State":{"Running":True}}), mock.patch.object(guard.time,"monotonic",side_effect=lambda:tick[0]), mock.patch.object(guard.time,"sleep",side_effect=lambda n:tick.__setitem__(0,tick[0]+n)):
            self.assertEqual(guard.stop_client(CID,events.append),"still_running")
        self.assertEqual(commands,[["docker","kill","--signal","INT",CID],["docker","stop","--timeout","10",CID]])
        self.assertGreaterEqual(tick[0],20)
        with self.assertRaises(ValueError): guard.stop_client(NAME,events.append)


if __name__=="__main__": unittest.main(verbosity=2)
