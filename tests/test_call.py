import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import call_agent as ca, phone_control as phone
print(ca._third_person("tell her I'll be late today and might not make it for dinner"))
print(ca._third_person("inform her that I am stuck in traffic"))
# fake conversation
class A:
    played=[]
    def play(s,b): pass
    turns=[b"x", b"x"]
    def listen(s, **k): return s.turns.pop(0) if s.turns else None
ca._synth=lambda t: b""
heard=iter(["Okay, that's fine. Tell him to drive safe.", "Bye"])
ca._stt=lambda b: next(heard, None)
replies=iter([{"say":"Sure, I'll tell him. Bye!","end":True}])
ca._think=lambda m: next(replies)
ca.call_state=lambda: "ACTIVE"
tr=[]
print(ca._conversation({"name":"Mom","number":"123","message":"tell her I'll be late today"}, A(), tr))
for w,t in tr: print(" ",w,":",t)
# prepare without libs
phone.ensure_connected=lambda: True
phone.resolve_number=lambda w: ("Mom","+911234")
r=ca.prepare("mom","tell her I'll be late")
print(type(r).__name__, getattr(r,"question",r))
