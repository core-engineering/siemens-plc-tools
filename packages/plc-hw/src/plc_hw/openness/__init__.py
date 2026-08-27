"""The CLR side of plc-hw.

Nothing outside this subpackage imports pythonnet, and ``import clr`` happens
inside a function so that ``plc hw diff`` works on a machine without TIA.
"""
