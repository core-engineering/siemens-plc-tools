# plc-hw

Versionable dump of TIA Portal hardware parameters.

An AutomationML export carries devices, order numbers, topology, I/O addresses and
F-addresses — but no module parameters, no CPU settings, no PROFINET timing, no
safety signatures. This package reads those through TIA Openness and writes them
as a deterministic YAML tree you can commit and diff.

```bash
plc hw dump --out deliverables/hardware-parameters
plc hw diff OLD NEW
plc hw check
```

`dump` and `check` need Windows with TIA Portal installed and the calling account
in the `Siemens TIA Openness` group. `diff` works anywhere.

The package never writes to TIA. There is no `SetAttribute` call in it.
