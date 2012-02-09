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

import pdb 
import math
from collections import defaultdict 

from .DtaError import DtaError
from .Link import Link
from .Movement import Movement
from .VehicleClassGroup import VehicleClassGroup
from .Utils import polylinesCross, lineSegmentsCross

class RoadLink(Link):
    """
    A RoadLink in a network.  Both nodes must be RoadNodes.
    
    """
    #: default level value
    DEFAULT_LEVEL = 0
    #: default lane width in feet
    DEFAULT_LANE_WIDTH_FEET = 12

    DIR_EB = "EB"
    DIR_WB = "WB"
    DIR_NB = "NB"
    DIR_SB = "SB"
    
    def __init__(self, id, startNode, endNode, reverseAttachedLinkId, facilityType, length,
                 freeflowSpeed, effectiveLengthFactor, responseTimeFactor, numLanes, 
                 roundAbout, level, label):
        """
        Constructor.
        
         * *id* is a unique identifier (unique within the containing network), an integer
         * *startNode*, *endNode* are Nodes
         * *reverseAttachedId* is the id of the reverse link, if attached; pass None if not
           attached
         * *facilityType* is a non-negative integer indicating the category of facility such
           as a freeway, arterial, collector, etc.  A lower number indicates a facility of
           higher priority, that is, higher capacity and speed.
         * *length* is the link length.  Pass None to automatically calculate it.
         * *freeflowSpeed* is in km/h or mi/h
         * *effectiveLengthFactor* is applied to the effective length of a vehicle while it is
           on the link.  May vary over time with LinkEvents
         * *responseTimeFactor* is the applied to the response time of the vehicle while it is
           on the link.  May vary over time with LinkEvents
         * *numLanes* is an integer
         * *roundAbout* is true/false or 1/0
         * *level* is an indicator to attribute vertical alignment/elevation. If None passed, will use default.
         * *label* is a link label. If None passed, will use default. 
         
        """
        Link.__init__(self, id, startNode, endNode, label)
        self._reverseAttachedLinkId     = reverseAttachedLinkId
        self._facilityType              = facilityType
        self._length                    = length
        self._freeflowSpeed             = freeflowSpeed
        self._effectiveLengthFactor     = effectiveLengthFactor
        self._responseTimeFactor        = responseTimeFactor

        if numLanes <= 0: 
            raise DtaError("RoadLink %d cannot have number of lanes = %d" % (self.getId(), numLanes))

        self._numLanes                  = numLanes
        self._roundAbout                = roundAbout
        if level:
            self._level                 = level
        else:
            self._level                 = RoadLink.DEFAULT_LEVEL

        self._lanePermissions           = {}  #: lane id -> VehicleClassGroup reference
        self._outgoingMovements         = []  #: list of outgoing Movements
        self._incomingMovements         = []  #: list of incoming Movements
        self._startShift                = None
        self._endShift                  = None
        self._shapePoints               = []  #: sequenceNum -> (x,y)
        self._centerline                = self.getCenterLine()

        self._simVolume = defaultdict(int)
        self._simMeanTT = defaultdict(float)

    def _validateInputTimes(self, startTimeInMin, endTimeInMin):
        """Checks that the input times belong to the simulation window"""
        if startTimeInMin >= endTimeInMin:
            raise DtaError("Invalid time bin (%d %s). The end time cannot be equal or less "
                                "than the end time" % (startTimeInMin, endTimeInMin))

        if startTimeInMin < self.simStartTimeInMin or endTimeInMin > \
                self.simEndTimeInMin:
            raise DtaError('Time period from %d to %d is out of '
                                   'simulation time' % (startTimeInMin, endTimeInMin))

    def _checkInputTimeStep(self, startTimeInMin, endTimeInMin):
        """Checks if the difference of the input times is equal to the simulation time step"""
        #TODO which check should I keep
        if endTimeInMin - startTimeInMin != self.simTimeStepInMin:
            raise DtaError('Time period from %d to %d is not '
                                   'is not in multiple simulation '
                                   'time steps %d' % (startTimeInMin, endTimeInMin,
                                                    self.simTimeStepInMin))
            

    def _checkOutputTimeStep(self, startTimeInMin, endTimeInMin):
        """Check that the difference of the input times is in multiples of the simulation time step"""
        if (endTimeInMin - startTimeInMin) % self.simTimeStepInMin != 0:
            raise DtaError('Time period from %d to %d is not '
                                   'is not in multiple simulation '
                                   'time steps %d' % (startTimeInMin, endTimeInMin,
                                                    self.simTimeStepInMin))

    def _hasMovementVolumes(self, startTimeInMin, endTimeInMin):
        """Return True if at least one movement has a volume 
        greater than 0"""
        for mov in self.iterOutgoingMovements():
            if mov.getSimVolume(startTimeInMin, endTimeInMin) > 0:
                return True
        return False

    def getSimFlow(self, startTimeInMin, endTimeInMin):
        """Get the simulated flow in vph"""
        volume = self.getSimVolume(startTimeInMin, endTimeInMin)        
        return int(float(volume) / (endTimeInMin - startTimeInMin) * 60)

    def getSimVolume(self, startTimeInMin, endTimeInMin):
        """Return the volume on the link from startTimeInMin to endTimeInMin"""

        self._validateInputTimes(startTimeInMin, endTimeInMin)
        self._checkOutputTimeStep(startTimeInMin, endTimeInMin)

        if self.getNumOutgoingMovements() > 0:
            return sum([mov.getSimVolume(startTimeInMin, endTimeInMin) 
                        for mov in self.iterOutgoingMovements()])
        else:
            result = 0
            for stTime, enTime in pairwise(range(startTimeInMin, endTimeInMin + 1, 
                                                 self.simTimeStepInMin)):
                result += self._simVolume[stTime, enTime]
            return result

    def getSimTTInMin(self, startTimeInMin, endTimeInMin):
        """Get the average travel time of the vehicles traversing the link"""

        self._validateInputTimes(startTimeInMin, endTimeInMin)
        self._checkOutputTimeStep(startTimeInMin, endTimeInMin)

        start = startTimeInMin
        end = endTimeInMin

        totalFlow = self.getSimVolume(start, end)
        if totalFlow == 0:
            return self.getFreeFlowTTInMin()

        if not self._simMeanTT and not self._simVolume:
            totalTime = sum([ mov.getSimTTInMin(start, end) * mov.getSimVolume(start, end)
                          for mov in self.iterOutgoingMovements()])
            return totalTime / float(totalFlow)
        elif self._simMeanTT and self._simVolume:
            totalTime = 0
            totalFlow = 0
            for (stTime, enTime), flow in self._simVolume.iteritems():
                if stTime >= startTimeInMin and enTime <= endTimeInMin:

                    binTT = self._simMeanTT[(stTime, enTime)]

                    if flow == 0 and binTT == 0:
                        continue
                    elif flow > 0 and binTT > 0:
                        totalFlow += flow
                        totalTime += binTT * flow
                    else:                        
                        raise SimMovementError("Movement %s has flow: %f and TT: %f "
                                               "for time period from %d to %d"  % 
                                               (self.iid, flow, binTT, 
                                                startTimeInMin, endTimeInMin))

            return totalTime / float(totalFlow)
            
            if endTimeInMin - startTimeInMin != self.simTimeStepInMin:
                raise DtaError("Not implemeted yet")

            return self._simMeanTT[start, end]
        else:
            return self.lengthInMiles / float(self.vfree) * 60

    def getSimSpeedInMPH(self, startTimeInMin, endTimeInMin):

        self._validateInputTimes(startTimeInMin, endTimeInMin)
        self._checkOutputTimeStep(startTimeInMin, endTimeInMin)
        
        #TODO if the coordinate system is not in feet 
        # you are going to have a problem
        tt = self.getSimTTInMin(startTimeInMin, endTimeInMin)
        speedInMPH = self.getLengthInMiles() / (tt / 60.)
        return speedInMPH

    def getObsMeanTT(self, startTimeInMin, endTimeInMin):
        """Get the observed mean travel time of the link in minutes"""
        raise Exception("Not implemented yet")
        return self._obsMeanTT[startTimeInMin, endTimeInMin]
            
    def getObsSpeedInMPH(self, startTimeInMin, endTimeInMin):
        """Get the observed speed of specified time period"""
        raise Exception("Not implemented yet")
        return self._obsSpeed[startTimeInMin, endTimeInMin]
    
    def setSimVolume(self, startTimeInMin, endTimeInMin, volume):
        """
        Set the simulated volume on the edge provided that the edge 
        does not have any emanating movements
        """
        self._validateInputTimes(startTimeInMin, endTimeInMin)
        self._checkInputTimeStep(startTimeInMin, endTimeInMin)

        if self._hasMovementVolumes(startTimeInMin, endTimeInMin):
            raise DtaError('Cannoot set the simulated volume on the edge %s'
                               'because there is at least one emanating '
                               'movement with volume greater than zero ' %
                               str(self.iid))

        if self.getNumOutgoingMovements() > 1:
            raise DtaError('Cannot set the simulated volume of the edge %s'
                               'with one or more emanating movements. Please'
                               ' set the volume of the movements' % str(self.iid))
        elif self.getNumOutgoingMovements() == 1:
            for emanatingMovement in self.iterOutgoingMovements():
                emanatingMovement.setSimVolume(startTimeInMin, endTimeInMin, volume)
        else:
            self._simVolume[startTimeInMin, endTimeInMin] = volume
        
    def setSimTTInMin(self, startTimeInMin, endTimeInMin, averageTTInMin):
        """
        Set the simulated travel time on the link for the particular input period
        """
        self._validateInputTimes(startTimeInMin, endTimeInMin)
        self._checkInputTimeStep(startTimeInMin, endTimeInMin)

        #TODO the input period should be in multiples of the simTimeStep        
        if startTimeInMin < self.simStartTimeInMin or endTimeInMin > \
                self.simEndTimeInMin:
            raise DtaError('Time period from %d to %d is out of '
                                   'simulation time' % (startTimeInMin, endTimeInMin))

        if endTimeInMin - startTimeInMin != self.simTimeStepInMin:
            raise DtaError('Not implemetd yet. Time period is different than the time step.')


        if self.getNumOutgoingMovements() > 1:
            raise DtaError('Cannot set the simulated travel time of the edge %s'
                               'with one or more emanating movements. Please'
                               ' set the time of the movements instead' % str(self.iid))
        elif self.getNumOutgoingMovements() == 1:
            if averageTTInMin == 0:
                return
            for emanatingMovement in self.iterOutgoingMovements():
                emanatingMovement.setSimTTInMin(startTimeInMin, endTimeInMin, averageTTInMin)
        else:
            if averageTTInMin == 0:
                return
            if self.getSimVolume(startTimeInMin, endTimeInMin) == 0:
                raise DtaError('Cannot set the travel time on edge %s because it has zero flow' % self.iid_)

            self._simMeanTT[startTimeInMin, endTimeInMin] = averageTTInMin
                        
    def addLanePermission(self, laneId, vehicleClassGroup):
        """
        Adds the lane permissions for the lane numbered by *laneId* (outside lane is lane 0, increases towards inside edge.)
        """
        if not isinstance(vehicleClassGroup, VehicleClassGroup):
            raise DtaError("RoadLink addLanePermission() called with invalid vehicleClassGroup %s" % str(vehicleClassGroup))
        
        if laneId < 0 or laneId >= self._numLanes:
            raise DtaError("RoadLink addLanePermission() called with invalid laneId %d; numLanes = %d" % 
                           (laneId, self._numLanes))
        
        self._lanePermissions[laneId] = vehicleClassGroup
        
    def addShifts(self, startShift, endShift):
        """
         * *startShift*: the shift value of the first segment of the link, that is, the number of lanes from
           the center line of the roadway that the first segment is shifted.
         * *endShift*: End-shift: the shift value of the last segment of the link, that is, the number of 
           lanes from the center line of the roadway that the last segment is shifted.
        """
        self._startShift    = startShift
        self._endShift      = endShift

    def getNumOutgoingMovements(self):
        """
        Returns the number of outgoing movements
        """
        return len(self._outgoingMovements)
    
    def getShifts(self):
        """
        Returns the *startShift* and *endShift* ordered pair, or (None,None) if it wasn't set.
        See addShifts() for details.
        """
        return (self._startShift, self._endShift)
    
    def addShapePoint(self, x, y):
        """
        Append a shape point to the link
        """
        self._shapePoints.append((x,y))

    def getNumShapePoints(self):
        """
        Return the number of shapepoints this link has
        """
        return len(self._shapePoints)

    def hasOutgoingMovement(self, nodeId):
        """
        Return True if the link has an outgoing movement towards nodeId
        """
        for mov in self.iterOutgoingMovements():
            if mov.getDestinationNode().getId() == nodeId:
                return True
        return False
    
    def addOutgoingMovement(self, movement):
        """
        Adds the given movement.
        """
        if not isinstance(movement, Movement):
            raise DtaError("RoadLink addOutgoingMovement() called with invalid movement %s" % str(movement))
        
        if movement.getIncomingLink() != self:
            raise DtaError("RoadLink addOutgoingMovement() called with inconsistent movement" % str(movement))

        if self.hasOutgoingMovement(movement.getDestinationNode().getId()):
            raise DtaError("RoadLink %s addOutgoingMovement() called to add already "
                           "existing movement" % str(movement))

        #if not movement.getVehicleClassGroup().allowsAll():
        #    raise DtaError("RoadLink %s addOutgoingMovement() called to add movement "
        #                   "with lane permissions %s" % (str(movement),
        #                                                 str(movement.getVehicleClassGroup())))
                    
        self._outgoingMovements.append(movement)
        movement.getOutgoingLink()._incomingMovements.append(movement)
    
    def iterOutgoingMovements(self):
        """
        Iterator for the outgoing movements of this link
        """
        return iter(self._outgoingMovements)

    def getNumIncomingMovements(self):
        """
        Returns the number of incoming movements
        """
        return len(self._incomingMovements)

    def removeOutgoingMovement(self, movementToRemove):
        """
        Delete the input movement
        """
        if not isinstance(movementToRemove, Movement):
            raise DtaError("RoadLink %s deleteOutgoingMovement() "
                           "called with invalid movement %s" % str(movementToRemove))
        
        if movementToRemove.getIncomingLink() != self:
            raise DtaError("RoadLink %s deleteOutgoingMovement() called with inconsistent movement" % str(movementToRemove))

        if not movementToRemove in self._outgoingMovements:
            raise DtaError("RoadLink %s deleteOutgoingMovement() called to delete "
                           "inexisting movement" % str(movementToRemove))

        self._outgoingMovements.remove(movementToRemove)
        movementToRemove.getOutgoingLink()._incomingMovements.remove(movementToRemove)

    def iterIncomingMovements(self):
        """
        Iterator for the incoming movements of this link
        """
        return iter(self._incomingMovements)

    def getNumLanes(self):
        """
        Return the number of lanes.
        """
        return self._numLanes

    def getLength(self):
        """
        Return the  length of the link in feet
        """
        if self._length != -1:
            return self._length 
        else:
            return self.euclideanLength()
        
    def getCenterLine(self):
        """
        Offset the link to the right 0.5*numLanes*:py:attr:`RoadLink.DEFAULT_LANE_WIDTH_FEET` and 
        return a tuple of two points (each one being a tuple of two floats) representing the centerline 
        """

        dx = self._endNode.getX() - self._startNode.getX()
        dy = self._endNode.getY() - self._startNode.getY() 

        length = self.euclideanLength() # dx ** 2 + dy ** 2

        if length == 0:
            length = 1

        scale = self.getNumLanes() * RoadLink.DEFAULT_LANE_WIDTH_FEET / 2.0 / length 

        xOffset = dy * scale
        yOffset = - dx * scale 

        self._centerline = ((self._startNode.getX() + xOffset, self._startNode.getY() + yOffset),
                            (self._endNode.getX() + xOffset, self._endNode.getY() + yOffset))

        return self._centerline

    def getOutline(self, scale=1):
        """
        Return the outline of the link as a linearRing of points
        in clockwise order. If scale the pysical outline of the link
        will be return using the number of lanes attribute to determine
        the boundries of the outline.
        """

        dx = self._endNode.getX() - self._startNode.getX()
        dy = self._endNode.getY() - self._startNode.getY() 

        length = self.euclideanLength() # dx ** 2 + dy ** 2

        if length == 0:
            length = 1

        scale = self.getNumLanes() * RoadLink.DEFAULT_LANE_WIDTH_FEET / length * scale

        xOffset = dy * scale
        yOffset = - dx * scale 

        outline = ((self._startNode.getX(), self._startNode.getY()),
                   (self._endNode.getX(), self._endNode.getY()),
                   (self._endNode.getX() + xOffset, self._endNode.getY() + yOffset),
                   (self._startNode.getX() + xOffset, self._startNode.getY() + yOffset))

        return outline


    def getMidPoint(self):
        """
        Return the midpoint of the link's centerline as a tuple of two floats
        """
        
        return ((self._centerline[0][0] + self._centerline[1][0]) / 2.0,
                (self._centerline[0][1] + self._centerline[1][1]) / 2.0)
                
    def isRoadLink(self):
        """
        Return True this Link is RoadLink
        """
        return True

    def isConnector(self):
        """
        Return True if this Link is a Connector
        """
        return False 

    def isVirtualLink(self):
        """
        Return True if this LInk is a VirtualLink
        """
        return False

    def getOutgoingMovement(self, nodeId):
        """
        Return True if the link has an outgoing movement towards nodeId
        """
        for mov in self.iterOutgoingMovements():
            if mov.getDestinationNode().getId() == nodeId:
                return mov
        raise DtaError("RoadLink from %d to %d does not have a movement to node %d" % (self._startNode.getId(),
                                                                                       self._endNode.getId(),
                                                                                       nodeId))
    def setNumLanes(self, numLanes):
        """
        Sets the number of lanes to the given value
        """ 
        self._numLanes = numLanes 
    
    def getAcuteAngle(self, other):
        """
        Return the acute angle (0, 180) between this link and the input one.
        Both links are considered as line segments from start to finish (shapepoints 
        are not taken into account).
        """

        if self == other:
            return 0

        if self.getStartNode().getX() == other.getStartNode().getX() and \
                self.getStartNode().getY() == other.getEndNode().getY() and \
                self.getEndNode().getX() == other.getEndNode().getX() and \
                self.getEndNode().getY() == other.getEndNode().getY():
            return 0

        if self.getStartNode() == other.getEndNode() and \
                self.getEndNode() == other.getStartNode():
            return 180 

        dx1 = self.getEndNode().getX() - self.getStartNode().getX()
        dy1 = self.getEndNode().getY() - self.getStartNode().getY()
        
        dx2 = other.getEndNode().getX() - other.getStartNode().getX()
        dy2 = other.getEndNode().getY() - other.getStartNode().getY()


        length1 = math.sqrt(dx1 ** 2 + dy1 ** 2)
        length2 = math.sqrt(dx2 ** 2 + dy2 ** 2)

        if length1 == 0:
            raise DtaError("The length of link %d cannot not be zero" % self.getId())
        if length2 == 0:
            raise DtaError("The length of link %d cannot not be zero" % other.getId())

        if abs((dx1 * dx2 + dy1 * dy2) / (length1 * length2)) > 1:
            if abs((dx1 * dx2 + dy1 * dy2) / (length1 * length2)) - 1 < 0.00001:
                return 0
            else:
                raise DtaError("cannot apply getAcute angle from %d to %d" % (self.getId(), other.getId()))            
        return abs(math.acos((dx1 * dx2 + dy1 * dy2) / (length1 * length2))) / math.pi * 180.0
    
    def isOverlapping(self, other):
        """
        Return True if the angle between the two links (measured using their endpoints) is less than 1 degree
        """
        if self.getAcuteAngle(other) <= 1.0:
            return True
        return False

    def getOrientation(self):
        """
        Returns the angle of the link in degrees from the North
        measured clockwise. The link shape is taken into account.
        """
        if self._shapePoints:
            x1, y1 = self._shapePoints[-2]
            x2, y2 = self._shapePoints[-1]
        else:
            x1 = self.getStartNode().getX()
            y1 = self.getStartNode().getY()
            x2 = self.getEndNode().getX()
            y2 = self.getEndNode().getY()

        if x2 > x1 and y2 <= y1:   # 2nd quarter
            orientation = math.atan(math.fabs(y2-y1)/math.fabs(x2-x1)) + math.pi/2
        elif x2 <= x1 and y2 < y1:   # 3th quarter
            orientation = math.atan(math.fabs(x2-x1)/math.fabs(y2-y1)) + math.pi
        elif x2 < x1 and y2 >= y1:  # 4nd quarter 
            orientation = math.atan(math.fabs(y2-y1)/math.fabs(x2-x1)) + 3 * math.pi/2
        elif x2 >= x1 and y2 > y1:  # 1st quarter
            orientation = math.atan(math.fabs(x2-x1)/math.fabs(y2-y1))
        else:
            orientation = 0.0

        return orientation * 180 / math.pi
        
    def getDirection(self):
        """Return the direction of the link as one of 
        EB, NB, WB, EB"""

        orientation = self.getOrientation()
        if 315 <= orientation or orientation < 45:
            return RoadLink.DIR_NB
        elif 45 <= orientation < 135:
            return RoadLink.DIR_EB
        elif 135 <= orientation < 225:
            return RoadLink.DIR_SB
        else:
            return RoadLink.DIR_WB
        
        
        

