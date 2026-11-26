import gpiozero
from collections import UserDict
import os
import sys
CANIOS = [ 4, 14, 15, 17, 18, 27, 22, 23, 24, 10, 9, 25, 11, 8, 7, 0, 1, 5, 6, 12, 13, 19, 16, 26]

KL15 = 3
KL30 = 2

class CanSwitchMatrix(UserDict):    
    CANS = []
    def show(self):
        print([can.is_active for can in self.CANS])
            
    pass

def relais_factory():
    err = 0
    can_relais = CanSwitchMatrix()
    all_can_pins = []
    for id, pin in enumerate(CANIOS, 1):
        print (f"CAN{id}: {pin}", end = " : ")
        try:
            name = f"CAN{id}"
            pin = gpiozero.LED(pin)
            can_relais[name] = pin
            print(f"OK {can_relais[name]}")
            setattr(can_relais, name, can_relais[name])
            all_can_pins.append(pin)
        except Exception as e:
            print(f"FAIL {e}")
    setattr(can_relais, "CANS", all_can_pins)            
    can_relais["KL15"] = gpiozero.LED(KL15)
    setattr(can_relais, "KL15", can_relais["KL15"])
    can_relais["KL30"] = gpiozero.LED(KL30)
    setattr(can_relais, "KL30", can_relais["KL30"])
    return can_relais

def hw29_kl15_kl30_on():
    REL.KL30.on()
    REL.KL15.on()

def hw29_500k5M_on():
    set_can_relais("500k5M", ["Can2", "Can9", "Can13", "Can14", "Can15", "Can16", "Can17", "Can18", "Can19"])

def hw29_500k_on():
    set_can_relais("500k", ["Can3", "Can5", "Can6", "Can8", "Can10", "Can11", "Can12", "Can20"])

def hw29_voicetocan():
    set_can_relais("voice", ["Can1"])

def hw29_can_relais_off():
    set_can_relais("all", [f"Can{c}" for c in range(1,20)], False)

def set_can_relais(diag, can_list, stateOn = True):
    print(f"Enable {diag} {can_list}")
    for can in can_list:
        if stateOn:
            print(f"  - Enable {can}")
            REL[can.upper()].on()
        else:
            print(f"  - Disable {can}")
            REL[can.upper()].off()

def persist_pin_state():
    # os._exit ends the process without running gpiozero's shutdown handler, 
    # so the pins are never switched back to input. 
    print("Persist pin state")
    os._exit(0)


REL = None

def main():
    global REL    
    REL = relais_factory()
    hw29_kl15_kl30_on()
    hw29_500k5M_on()
    hw29_500k_on()
    #hw29_voicetocan()
    if sys.flags.interactive:
        # python runs with -i
        pass
    else:
        # python runs as "programm"
        persist_pin_state()
    

if __name__ == "__main__":
    main()
    