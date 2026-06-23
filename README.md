# FuG Control

## Simple command line interface for controlling a FuG power supply.

This allows to control a FuG power supply (e.g. [HCP14](https://www.xppower.com/product/HCP14-Series)) with an Ethernet interface.

Additionally, when run with the command-line argument `-i`, the 
interlock signal from a Tofwerk TOF power supply is monitored and the FuG output
is switched off if an interlock occurs.


![](./screenshot.jpg)

### Usage
```
python FuG_Control.py [-h] [-i]
```
