__copyright__   = "Copyright 2011 SFCTA"
__license__     = """
    This file is part of DTA.

    DTA is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    DTA is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with DTA.  If not, see <http://www.gnu.org/licenses/>.
"""

class VehicleType:
    """
    Class that represents a vehicle type.
    """
    
    def __init__(self, name, className, length, responseTime):
        """
        Constructor.
        
         *name* is the vehicle type name, e.g. ``small_truck``
         *className* a broader class, e.g. ``truck``
         *length* is the effective length (units?)
         *responseTime* is ?
         
        """
        self.name           = name
        self.className      = className
        self.length         = length
        self.responseTime   = responseTime