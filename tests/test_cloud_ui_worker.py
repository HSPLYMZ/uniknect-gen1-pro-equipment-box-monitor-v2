import sys, types, importlib.util, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
D=Path(__file__).resolve().parents[1]/"device"
sys.path.insert(0,str(D))


def load(name, filename, modules):
    spec=importlib.util.spec_from_file_location(name,D/filename)
    mod=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,modules):spec.loader.exec_module(mod)
    return mod


class CloudUiWorkerTests(unittest.TestCase):
    def test_four_page_cycle_and_dirty_network_rows(self):
        m=load("cloud_display_test","display.py",{"machine":types.SimpleNamespace()})
        ui=m.Display.__new__(m.Display)
        ui.page=2;ui.button=types.SimpleNamespace(poll=lambda *a:"next")
        ui.button_error=None
        ui.poll_button(0,lambda a,b:a-b);self.assertEqual(ui.page,3)
        ui.poll_button(0,lambda a,b:a-b);self.assertEqual(ui.page,0)
        ui.page=3
        lines=[]
        lcd=types.SimpleNamespace(WIDTH=160,HEIGHT=128,RED=1,BLACK=0,WHITE=2,CYAN=3,
            fill_screen=lambda *a:None,fill_rectangle=lambda *a:None,flush=lambda:None,
            show_string=lambda x,y,s,*a:lines.append(s))
        ui.lcd=lcd
        status={"network":"ONLINE","rsrp_dbm":-75,"sinr_db":37.0,"phase":"PAUSE","phase_s":180,
                "sent":12,"last_result":"CALLED","budget":108}
        self.assertTrue(ui.render({}, {}, [], "ONLINE",0,0,420,0,cloud_status=status))
        self.assertIn("LTE RSRP:-75dBm",lines)
        self.assertIn("LTE SINR:37.0dB",lines)
        self.assertIn("TX:PAUSE 03:00",lines)
        self.assertTrue(all(len(s)<=26 for s in lines))
        lines.clear()
        self.assertFalse(ui.render({}, {}, [], "ONLINE",0,0,420,0,cloud_status=status))
        status.update(rsrp_dbm=None,sinr_db=None,phase="ENDED",phase_s=0)
        self.assertTrue(ui.render({}, {}, [], "ONLINE",0,0,1801,0,cloud_status=status))
        self.assertIn("LTE RSRP:--dBm",lines)
        self.assertIn("LTE SINR:--dB",lines)
        self.assertIn("TX:ENDED 00:00",lines)

    def test_transport_sixty_none_return_calls_and_stop_latch(self):
        calls=[];pings=[]
        sdk=types.SimpleNamespace(init=lambda:True,setProductInfo=lambda *a:True,
            setDK=lambda *a:None,setServer=lambda *a:True,setVer=lambda *a:None,
            setLifetime=lambda *a:True,
            setEventCb=lambda *a:None,start=lambda:True,state=lambda:True,
            sendTsl=lambda mode,data:calls.append((clock.now,dict(data))),
            ackTsl=lambda *a:None,stop=lambda:None,
            qth_file=types.SimpleNamespace(write_file=None))
        sdk.qth_dmp=types.SimpleNamespace(_mqtt_client=types.SimpleNamespace(ping=lambda:pings.append(clock.now)))
        net=types.SimpleNamespace(init=lambda:True,get_signal=lambda:(-75,118))
        mod=load("cloud_transport_test","qth_transport.py",{"Qth":sdk,
            "quectel":types.SimpleNamespace(Network=lambda:net),
            "qth_compat":types.SimpleNamespace(install=lambda q:None)})
        clock=types.SimpleNamespace(now=0)
        clock.ticks_ms=lambda:clock.now
        clock.ticks_diff=lambda a,b:a-b
        mod.time=clock
        cfg=types.SimpleNamespace(ENABLE_QTH=True,QTH_PRODUCT_KEY="p",QTH_PRODUCT_SECRET="s",
                                  QTH_DEVICE_KEY="d",QTH_SERVER="example")
        worker=mod.QthTransport(cfg)
        from cloud_policy import TrafficBudget
        with tempfile.TemporaryDirectory() as d, patch("builtins.print"), patch.dict(sys.modules,{
                "Qth":sdk,"quectel":types.SimpleNamespace(Network=lambda:net),
                "qth_compat":types.SimpleNamespace(install=lambda q:None)}):
            mod.TrafficBudget=lambda path,now,diff:TrafficBudget(str(Path(d)/"b"),now,diff)
            for now in range(0,1870000,200):
                clock.now=now
                worker.submit({"temperature_c":0,"humidity_pct":50,"light_adc_u16":12},now)
                worker.connect_if_due(now,clock.ticks_diff,None)
                worker.send_one(None,now)
            worker.close()
        self.assertEqual(len(calls),60)
        self.assertTrue(all(v[5]==7 for t,v in calls))
        self.assertEqual(worker.last_result,"CALLED")
        self.assertEqual(worker.status(clock.now)["phase"],"ENDED")
        self.assertEqual(worker.status(-1)["phase"],"ENDED")
        self.assertEqual(worker.rsrp,-75)
        self.assertEqual(worker.sinr,35.5)
        self.assertGreaterEqual(len(pings),30)
        self.assertTrue(any(t<300000 for t in pings))
        self.assertTrue(any(t>=1800000 for t in pings))
        self.assertEqual(worker.ping_errors,0)
        self.assertGreaterEqual(worker.budget.remaining(),65)  # PING consumes no traffic credits.
        stale=worker.status(clock.now+90001)
        self.assertIsNone(stale['rsrp_dbm'])
        self.assertIsNone(stale['sinr_db'])


if __name__=="__main__":unittest.main()
