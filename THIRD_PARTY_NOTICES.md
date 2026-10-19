# Third-party notices

Shilpa depends on these open-source parts libraries (installed from PyPI, not vendored):

| Package | Used for | Licence |
|---|---|---|
| [bd_warehouse](https://github.com/gumyr/bd_warehouse) | ISO fasteners (`shilpa/catalog/fasteners.py`); screws, nuts, washers, bearing data, O-rings, circlips and keys from its dimension tables (`shilpa/catalog/warehouse.py`); pipe and ASME B16.5 flange tables, OpenBuilds parts, sprockets and worm gears (`shilpa/catalog/mechanical.py`) | Apache-2.0 |
| [py_gearworks](https://github.com/GarryBGoode/py_gearworks) | Involute gears and racks (`shilpa/catalog/gears.py`) | Apache-2.0 |
| [bd_vslot](https://github.com/keeeal/bd-vslot) | V-slot wheels and T-nuts (`shilpa/catalog/vslot.py`) | MIT |

## Adapted code

`shilpa/catalog/vslot.py` contains the 20-series V-slot cross-section outlines and cell
layout logic adapted from bd_vslot (`bd_vslot/rails.py`), under the following licence:

```
MIT License

Copyright (c) 2024 James Keal

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
