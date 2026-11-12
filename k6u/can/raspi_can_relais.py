import gpiozero
from collections import UserDict
CANIOS = [ 4, 14, 15, 17, 18, 27, 22, 23, 24, 10, 9, 25, 11, 8, 7, 0, 1, 5, 6, 12, 13, 19, 16, 26]

KL15 = 2
KL30 = 3

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


REL = None

def main():
    global REL
    print("hello", __file__)
    
    REL = relais_factory()


if __name__ == "__main__":
    main()
