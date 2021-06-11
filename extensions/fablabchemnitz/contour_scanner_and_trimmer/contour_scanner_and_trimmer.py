#!/usr/bin/env python3

'''
Extension for InkScape 1.0+
 - WARNING: HORRIBLY SLOW CODE. PLEASE HELP TO MAKE IT USEFUL FOR LARGE AMOUNT OF PATHS
 - add options:
    - efficiently find overlapping colinear lines by checking their slope/gradient
        - get all lines and sort by slope; kick out all slopes which are unique. We only want re-occuring slopes
        - intersects() is equivalent to the OR-ing of contains(), crosses(), equals(), touches(), and within().
          So there might be some cases where two lines intersect eachother without crossing, 
          in particular when one line contains another or when two lines are equals.
        - crosses() returns True if the dimension of the intersection is less than the dimension of the one or the other.
          So if two lines overlap, they won't be considered as "crossing". intersection() will return a geometric object.
    - replace trimmed paths by bezier paths (calculating lengths and required t parameter)
    - find more duplicates
        - overlapping lines in sub splits
        - overlapping in original selection
        - duplicates in original selection
        - duplicates in split bezier
        - ...
    - maybe option: convert abs path to rel path
    - maybe option: convert rel path to abs path
        replacedelement.path = replacedelement.path.to_absolute().to_superpath().to_path()
    - maybe option: break apart while keeping relative/absolute commands (more complex and not sure if we have a great advantage having this)

    
- important to notice
    - this algorithm might be really slow. Reduce flattening quality to speed up
    - the code quality is horrible. We need a lot of asserts and functions to structure that stuff
    - try to adjust snap tolerance and flatness in case of errors, like
      poly_point_isect.py: "KeyError: 'Event(0x21412ce81c0, s0=(47.16, 179.1),
      s1=(47.17, 178.21), p=(47.16, 179.1), type=2, slope=-88.9999999999531)'"
    - this extension does not check for strange paths. Please ensure that your path 'd'
      data is valid (no pointy paths, no duplicates, etc.)
    - we do not use shapely to look for intersections by cutting each line against
      each other line (line1.intersection(line2) using two for-loops) because this 
      kind of logic is really really slow for huge amount. You could use that only 
      for ~50-100 elements. So we use special algorihm (Bentley-Ottmann)
    - Cool tool to visualize sweep line algorithm Bentley-Ottmann: https://bl.ocks.org/1wheel/464141fe9b940153e636

- things to look at more closely:
    - https://gis.stackexchange.com/questions/203048/split-lines-at-points-using-shapely
    - https://stackoverflow.com/questions/34754777/shapely-split-linestrings-at-intersections-with-other-linestrings
        - There are floating point precision errors when finding a point on a line. Use the distance with an appropriate threshold instead.
            - line.within(point)  # False
            - line.distance(point)  # 7.765244949417793e-11
            - line.distance(point) < 1e-8  # True
    - https://bezier.readthedocs.io/en/stable/python/reference/bezier.hazmat.clipping.html / https://github.com/dhermes/bezier
    - De Casteljau Algorithm

Author: Mario Voigt / FabLab Chemnitz
Mail: mario.voigt@stadtfabrikanten.org
Date: 09.08.2020 (extension originally called "Contour Scanner")
Last patch: 11.06.2021
License: GNU GPL v3

'''

import sys
import os
import copy
from lxml import etree
import poly_point_isect
from poly_point_isect import isect_segments
import inkex
from inkex import transforms, bezier, PathElement, Color, Circle
from inkex.bezier import csplength
from inkex.paths import Path, CubicSuperPath
from shapely.geometry import LineString, Point, MultiPoint
from shapely.ops import snap, split
from shapely import speedups
if speedups.available:
    speedups.enable()


idPrefix = "subsplit"
intersectedVerb = "-intersected-"

class ContourScannerAndTrimmer(inkex.EffectExtension):

    def break_contours(self, element, breakelements = None):
        ''' 
        this does the same as "CTRL + SHIFT + K"
        This functions honors the fact of absolute or relative paths!
         '''
        if breakelements == None:
            breakelements = []
        if element.tag == inkex.addNS('path','svg'):
            parent = element.getparent()
            idx = parent.index(element)
            idSuffix = 0
            #raw = str(element.path).split()
            raw = element.path.to_arrays() 
            subPaths = []
            prev = 0
            for i in range(len(raw)): # Breaks compound paths into simple paths
                #if raw[i][0].upper() == 'M' and i != 0:
                if raw[i][0] == 'M' and i != 0:
                    subPath = raw[prev:i]
                    subPaths.append(Path(subPath))
                    prev = i
            subPaths.append(Path(raw[prev:])) #finally add the last path

            for subPath in subPaths:
                replacedelement = copy.copy(element)
                oldId = replacedelement.get('id')
                csp = CubicSuperPath(subPath)
                if len(subPath) > 1 and csp[0][0] != csp[0][1]: #avoids pointy paths like M "31.4794 57.6024 Z"
                    replacedelement.path = subPath
                    replacedelement.set('id', oldId + str(idSuffix))
                    parent.insert(idx, replacedelement)
                    idSuffix += 1
                    breakelements.append(replacedelement)
            element.delete()
        for child in element.getchildren():
            self.break_contours(child, breakelements)
        return breakelements


    def get_child_paths(self, element, elements = None):
        ''' a function to get child paths from elements (used by "handling groups" option) '''
        if elements == None:
            elements = []
        if element.tag == inkex.addNS('path','svg'):
                elements.append(element)
        for child in element.getchildren():
            self.get_child_paths(child, elements)
        return elements


    def get_path_elements(self):
        ''' get all path elements, either from selection or from whole document. Uses options '''
        pathElements = []
        if len(self.svg.selected) == 0: #if nothing selected we search for the complete document
            pathElements = self.document.xpath('//svg:path', namespaces=inkex.NSS)
        else: # or get selected paths (and children) and convert them to shapely LineString objects
            if self.options.handle_groups is False:
                pathElements = list(self.svg.selection.filter(PathElement).values())
            else:
                for element in self.svg.selection.values():
                    pathElements = self.get_child_paths(element, pathElements)

        if len(pathElements) == 0:
            self.msg('Selection appears to be empty or does not contain any valid svg:path nodes. Try to cast your objects to paths using CTRL + SHIFT + C or strokes to paths using CTRL + ALT + C')
            exit(1)

        if self.options.break_apart is True:
            breakApartElements = None
            for pathElement in pathElements:
                breakApartElements = self.break_contours(pathElement, breakApartElements)
            pathElements = breakApartElements

        if self.options.show_debug is True:
            self.msg("total processing paths count: {}".format(len(pathElements)))

        return pathElements


    def find_group(self, groupId):
        ''' check if a group with a given id exists or not. Returns None if not found, else returns the group element '''
        groups = self.document.xpath('//svg:g', namespaces=inkex.NSS)
        for group in groups:
            #self.msg(str(layer.get('inkscape:label')) + " == " + layerName)
            if group.get('id') == groupId:
                return group
        return None


    def adjust_style(self, element):
        ''' Replace some style attributes of the given element '''
        if element.attrib.has_key('style'):
            style = element.get('style')
            if style:
                declarations = style.split(';')
                for i,decl in enumerate(declarations):
                    parts = decl.split(':', 2)
                    if len(parts) == 2:
                        (prop, val) = parts
                        prop = prop.strip().lower()
                        if prop == 'stroke-width':
                            declarations[i] = prop + ':' + str(self.svg.unittouu(str(self.options.strokewidth) +"px"))
                        if prop == 'fill':
                            declarations[i] = prop + ':none'
                element.set('style', ';'.join(declarations) + ';stroke:#000000;stroke-opacity:1.0')
        else:
            element.set('style', 'stroke:#000000;stroke-opacity:1.0')


    def line_from_segments(self, segs, i, decimals):
        '''builds a straight line for the segment i and the next segment i+2. Returns both point XY coordinates'''
        pseudoPath = Path(segs[i:i+2]).to_arrays()
        x1 = round(pseudoPath[0][1][-2], decimals)
        y1 = round(pseudoPath[0][1][-1], decimals)
        if pseudoPath[1][0] == 'Z': #some crappy code when the path is closed
            pseudoPathEnd = Path(segs[0:2]).to_arrays()
            x2 = round(pseudoPathEnd[0][1][-2], decimals)
            y2 = round(pseudoPathEnd[0][1][-1], decimals)
        else:
            x2 = round(pseudoPath[1][1][-2], decimals)
            y2 = round(pseudoPath[1][1][-1], decimals)
        return x1, y1, x2, y2


    def visualize_self_intersections(self, pathElement, selfIntersectionPoints):
        ''' Draw some circles at given point coordinates (data from array)'''
        selfIntersectionGroup = pathElement.getparent().add(inkex.Group(id="selfIntersectionPoints-{}".format(pathElement.attrib["id"])))
        selfIntersectionPointStyle = {'stroke': 'none', 'fill': self.options.color_self_intersections}
        for selfIntersectionPoint in selfIntersectionPoints:
            cx = selfIntersectionPoint[0]
            cy = selfIntersectionPoint[1]
            selfIntersectionPointCircle = Circle(cx=str(cx),
                            cy=str(cy),
                            r=str(self.svg.unittouu(str(self.options.dotsize_intersections / 2) + "px"))
                            )
            
            if pathElement.getparent() != self.svg.root:
                selfIntersectionPointCircle.transform = -pathElement.getparent().composed_transform()
            selfIntersectionPointCircle.set('id', self.svg.get_unique_id('selfIntersectionPoint-'))
            selfIntersectionPointCircle.style = selfIntersectionPointStyle
            selfIntersectionGroup.add(selfIntersectionPointCircle)


    def visualize_global_intersections(self, globalIntersectionPoints):
        ''' Draw some circles at given point coordinates (data from array)'''
        if len(globalIntersectionPoints) > 0: #only create a group and add stuff if there are some elements to work on 
            globalIntersectionGroup = self.svg.root.add(inkex.Group(id="globalIntersectionPoints"))
            globalIntersectionPointStyle = {'stroke': 'none', 'fill': self.options.color_global_intersections}
            for globalIntersectionPoint in globalIntersectionPoints:
                cx = globalIntersectionPoint.coords[0][0]
                cy = globalIntersectionPoint.coords[0][1]
                globalIntersectionPointCircle = Circle(cx=str(cx),
                    cy=str(cy),
                    r=str(self.svg.unittouu(str(self.options.dotsize_intersections / 2) + "px"))
                    )
                globalIntersectionPointCircle.set('id', self.svg.get_unique_id('globalIntersectionPoint-'))
                globalIntersectionPointCircle.style = globalIntersectionPointStyle
                globalIntersectionGroup.add(globalIntersectionPointCircle)


    def build_trim_line_group(self, subSplitLineArray, subSplitIndex, globalIntersectionPoints): 
        ''' make a group containing trimmed lines'''      
        
        #Check if we should skip or process the path anyway   
        isClosed = subSplitLineArray[subSplitIndex].attrib['originalPathIsClosed']
        if self.options.trimming_path_types == 'open_paths' and isClosed == 'True': return #skip this call
        elif self.options.trimming_path_types == 'closed_paths' and isClosed == 'False': return #skip this call
        elif self.options.trimming_path_types == 'both': pass
     
        csp = subSplitLineArray[subSplitIndex].path.to_arrays()
        ls = LineString([(csp[0][1][0], csp[0][1][1]), (csp[1][1][0], csp[1][1][1])])
        
        trimLineStyle = {'stroke': str(self.options.color_trimmed), 'fill': 'none', 'stroke-width': self.options.strokewidth}
           
        linesWithSnappedIntersectionPoints = snap(ls, globalIntersectionPoints, self.options.snap_tolerance)
        trimGroupId = 'shapely-' + subSplitLineArray[subSplitIndex].attrib['id'].split("_")[0] #split at "_" (_ from subSplitId)
        trimGroupParentId = subSplitLineArray[subSplitIndex].attrib['id'].split(idPrefix+"-")[1].split("_")[0]
        trimGroupParent = self.svg.getElementById(trimGroupParentId)
        trimGroupParentTransform = trimGroupParent.composed_transform()
        trimGroup = self.find_group(trimGroupId)
        if trimGroup is None:
            trimGroup = trimGroupParent.getparent().add(inkex.Group(id=trimGroupId))
          
        #apply isBezier and original path id information to group (required for bezier splitting the original path at the end)
        trimGroup.attrib['originalPathIsBezier'] = subSplitLineArray[subSplitIndex].attrib['originalPathIsBezier']
        trimGroup.attrib['originalPathId'] = subSplitLineArray[subSplitIndex].attrib['originalPathId']

        #split all lines against all other lines using the intersection points
        trimLines = split(linesWithSnappedIntersectionPoints, globalIntersectionPoints)

        splitAt = [] #if the sub split line was split by an intersecting line we receive two trim lines with same assigned original path id!
        prevLine = None
        for j in range(len(trimLines)):
            trimLineId = "{}-{}".format(trimGroupId, subSplitIndex)
            splitAt.append(trimGroupId)
            if splitAt.count(trimGroupId) > 1: #we detected a lines with intersection on
                trimLineId = trimLineId + self.svg.get_unique_id(intersectedVerb)
                '''
                so the previous lines was an intersection lines too. so we change the id to include the intersected verb
                (left side and right side of cut) - note: updating element 
                id sometimes seems not to work if the id was used before in Inkscape
                '''
                prevLine.attrib['id'] = trimGroupId + "-" + str(subSplitIndex) + self.svg.get_unique_id(intersectedVerb)
                prevLine.attrib['intersected'] = 'True' #some dirty flag we need
            prevLine = trimLine = inkex.PathElement(id=trimLineId)
            x, y = trimLines[j].coords.xy
            trimLine.path = [['M', [x[0],y[0]]], ['L', [x[1],y[1]]]]
            if trimGroupParentTransform is not None:
                trimLine.path = trimLine.path.transform(-trimGroupParentTransform)
            if self.options.apply_style_to_trimmed is False:
                trimLine.style = trimLineStyle
            else:
                trimLine.style = subSplitLineArray[subSplitIndex].attrib['originalPathStyle']
            trimGroup.add(trimLine)
        return trimGroup


    def remove_duplicates(self, allTrimGroups):
        ''' find duplicate lines in a given array [] of groups '''
        totalTrimPaths = []
        if self.options.reverse_removal_order is True:
            allTrimGroups = allTrimGroups[::-1]
        for trimGroup in allTrimGroups:
            for element in trimGroup:
                if element.path not in totalTrimPaths:
                    totalTrimPaths.append(element.path)
                else:
                    if self.options.show_debug is True:
                        self.msg("Deleting {}".format(element.get('id')))
                    element.delete()
            if len(trimGroup) == 0:
                if self.options.show_debug is True:
                    self.msg("Deleting {}".format(trimGroup.get('id')))
                trimGroup.delete()
                                

    def combine_nonintersects(self, allTrimGroups):
        ''' 
        combine and chain all non intersected sub split lines which were trimmed at intersection points before.
        - At first we sort out all lines by their id: 
            - if the lines id contains intersectedVerb, we ignore it
            - we combine all lines which do not contain intersectedVerb
        - Then we loop through that combined structure and chain their segments which touch each other
        Changes the style according to user setting.
        '''
        
        nonTrimLineStyle = {'stroke': str(self.options.color_nonintersected), 'fill': 'none', 'stroke-width': self.options.strokewidth}
        trimNonIntersectedStyle = {'stroke': str(self.options.color_combined), 'fill': 'none', 'stroke-width': self.options.strokewidth}
        
        for trimGroup in allTrimGroups:
            totalIntersectionsAtPath = 0
            combinedPath = None
            combinedPathData = Path()
            if self.options.show_debug is True:
                self.msg("trim group {} has {} paths".format(trimGroup.get('id'), len(trimGroup)))
            for pElement in trimGroup:
                pId = pElement.get('id')
                #if self.options.show_debug is True:
                #    self.msg("trim paths id {}".format(pId))
                if intersectedVerb not in pId:
                    if combinedPath is None:
                        combinedPath = pElement
                        combinedPathData = pElement.path
                    else:
                        combinedPathData += pElement.path
                        pElement.delete()
                else:
                    totalIntersectionsAtPath += 1
            if len(combinedPathData) > 0:
                segData = combinedPathData.to_arrays()
                newPathData = []
                newPathData.append(segData[0]) 
                for z in range(1, len(segData)): #skip first because we add it statically
                    if segData[z][1] != segData[z-1][1]:
                       newPathData.append(segData[z])
                if self.options.show_debug is True:
                    self.msg("trim group {} has {} combinable segments:".format(trimGroup.get('id'), len(newPathData)))     
                    self.msg("{}".format(newPathData))
                combinedPath.path = Path(newPathData)              
                if self.options.apply_style_to_trimmed is False:
                    combinedPath.style = trimNonIntersectedStyle         
                    if totalIntersectionsAtPath == 0:
                        combinedPath.style = nonTrimLineStyle
            else: #the group might consist of intersections only. than we have length of 0
                if self.options.show_debug is True:
                    self.msg("trim group {} has no combinable segments (contains only intersected trim lines)".format(trimGroup.get('id')))  
                       
         
    def trim_bezier(self, allTrimGroups):
        '''
        trim bezier path by checking the lengths and calculating global t parameter from the trimmed sub split lines groups
        This function does not work yet.
        '''  
        for trimGroup in allTrimGroups:
            if trimGroup.attrib.has_key('originalPathIsBezier') and trimGroup.attrib['originalPathIsBezier'] == "True":
                globalTParameters = []
                if self.options.show_debug is True:
                    self.msg("{}: count of trim lines = {}".format(trimGroup.get('id'), len(trimGroup)))
                totalLength = 0
                for trimLine in trimGroup:
                    ignore, lineLength = csplength(CubicSuperPath(trimLine.get('d')))
                    totalLength += lineLength
                if self.options.show_debug is True:
                    self.msg("total length = {}".format(totalLength))
                chainLength = 0
                for trimLine in trimGroup:
                    ignore, lineLength = csplength(CubicSuperPath(trimLine.get('d')))
                    chainLength += lineLength
                    if trimLine.attrib.has_key('intersected') or trimLine == trimGroup[-1]: #we may not used intersectedVerb because this was used for the affected left as well as the right side of the splitting. This would result in one "intersection" too much.
                        globalTParameter = chainLength / totalLength
                        globalTParameters.append(globalTParameter)
                        if self.options.show_debug is True:
                            self.msg("chain piece length = {}".format(chainLength))
                            self.msg("t parameter = {}".format(globalTParameter))
                        chainLength = 0
                if self.options.show_debug is True:
                    self.msg("Trimming the original bezier path {} at global t parameters: {}".format(trimGroup.attrib['originalPathId'], globalTParameters))
                for globalTParameter in globalTParameters:
                    csp = CubicSuperPath(self.svg.getElementById(trimGroup.attrib['originalPathId']))
                '''
                Sadly, those calculated global t parameters are useless for splitting because we cannot split the complete curve at a t parameter
                Instead we only can split a bezier by getting to commands which build up a bezier path segment.
                - we need to find those parts (segment pairs) of the original path first where the sub split line intersection occurs
                - then we need to calculate the t parameter
                - then we split the bezier part (consisting of two commands) and check the new intersection point. 
                  It should match the sub split lines intersection point.
                  If they do not match we need to adjust the t parameter or loop to previous or next bezier command to find intersection              
                '''
                

    def add_arguments(self, pars):
        pars.add_argument("--tab")
        
        #Settings - General
        pars.add_argument("--show_debug", type=inkex.Boolean, default=False, help="Show debug infos")
        pars.add_argument("--break_apart", type=inkex.Boolean, default=False, help="Break apart input paths into sub paths")
        pars.add_argument("--handle_groups", type=inkex.Boolean, default=False, help="Also looks for paths in groups which are in the current selection")
        pars.add_argument("--trimming_path_types", default="closed_paths", help="Process open paths by other open paths, closed paths by other closed paths, or all paths by all other paths")
        pars.add_argument("--flattenbezier", type=inkex.Boolean, default=True, help="Flatten bezier curves to polylines")
        pars.add_argument("--flatness", type=float, default=0.1, help="Minimum flatness = 0.001. The smaller the value the more fine segments you will get (quantization). Large values might destroy the line continuity.")
        pars.add_argument("--decimals", type=int, default=3, help="Accuracy for sub split lines / lines trimmed by shapely")
        pars.add_argument("--snap_tolerance", type=float, default=0.1, help="Snap tolerance for intersection points")

        #Scanning - Removing
        pars.add_argument("--remove_relative", type=inkex.Boolean, default=False, help="relative cmd")
        pars.add_argument("--remove_absolute", type=inkex.Boolean, default=False, help="absolute cmd")
        pars.add_argument("--remove_mixed", type=inkex.Boolean, default=False, help="mixed cmd (relative + absolute)")
        pars.add_argument("--remove_polylines", type=inkex.Boolean, default=False, help="polyline")
        pars.add_argument("--remove_beziers", type=inkex.Boolean, default=False, help="bezier")
        pars.add_argument("--remove_opened", type=inkex.Boolean, default=False, help="opened")
        pars.add_argument("--remove_closed", type=inkex.Boolean, default=False, help="closed")
        pars.add_argument("--remove_self_intersecting", type=inkex.Boolean, default=False, help="self-intersecting")

        #Scanning - Highlighting
        pars.add_argument("--highlight_relative", type=inkex.Boolean, default=False, help="relative cmd paths")
        pars.add_argument("--highlight_absolute", type=inkex.Boolean, default=False, help="absolute cmd paths")
        pars.add_argument("--highlight_mixed", type=inkex.Boolean, default=False, help="mixed cmd (relative + absolute) paths")
        pars.add_argument("--highlight_polylines", type=inkex.Boolean, default=False, help="polyline paths")
        pars.add_argument("--highlight_beziers", type=inkex.Boolean, default=False, help="bezier paths")
        pars.add_argument("--highlight_opened", type=inkex.Boolean, default=False, help="opened paths")
        pars.add_argument("--highlight_closed", type=inkex.Boolean, default=False, help="closed paths")
        pars.add_argument("--highlight_self_intersecting", type=inkex.Boolean, default=False, help="self-intersecting paths")
        pars.add_argument("--draw_subsplit", type=inkex.Boolean, default=False, help="Draw sub split lines (polylines)")
        pars.add_argument("--visualize_self_intersections", type=inkex.Boolean, default=False, help="self-intersecting path points")
        pars.add_argument("--visualize_global_intersections", type=inkex.Boolean, default=False, help="global intersection points")
 
        #Settings - Trimming
        pars.add_argument("--draw_trimmed", type=inkex.Boolean, default=False, help="Draw trimmed lines")
        pars.add_argument("--combine_nonintersects", type=inkex.Boolean, default=True, help="Combine non-intersected lines")
        pars.add_argument("--remove_duplicates", type=inkex.Boolean, default=True, help="Remove duplicate trim lines")
        pars.add_argument("--reverse_removal_order", type=inkex.Boolean, default=False, help="Reverses the order of removal. Relevant for keeping certain styles of elements")
        pars.add_argument("--keep_original_after_trim", type=inkex.Boolean, default=False, help="Keep original paths after trimming") 

        #Style - General Style
        pars.add_argument("--strokewidth", type=float, default=1.0, help="Stroke width (px)")   
        pars.add_argument("--dotsize_intersections", type=int, default=30, help="Dot size (px) for self-intersecting and global intersection points")
        pars.add_argument("--removefillsetstroke", type=inkex.Boolean, default=False, help="Remove fill and define stroke for original paths")
        pars.add_argument("--bezier_trimming", type=inkex.Boolean, default=False, help="If true we try to use the calculated t parameters from intersection points to receive splitted bezier curves")
        pars.add_argument("--apply_style_to_subsplits", type=inkex.Boolean, default=True, help="Apply highlighting styles to sub split lines.")
        pars.add_argument("--apply_style_to_trimmed", type=inkex.Boolean, default=True, help="Apply original path style to trimmed lines")
     
        #Style - Scanning Colors
        pars.add_argument("--color_subsplit", type=Color, default='1630897151', help="sub split lines")
        pars.add_argument("--color_relative", type=Color, default='3419879935', help="relative cmd paths")
        pars.add_argument("--color_absolute", type=Color, default='1592519679', help="absolute cmd paths")
        pars.add_argument("--color_mixed", type=Color, default='3351636735', help="mixed cmd (relative + absolute) paths")
        pars.add_argument("--color_polyline", type=Color, default='4289703935', help="polyline paths")
        pars.add_argument("--color_bezier", type=Color, default='258744063', help="bezier paths")
        pars.add_argument("--color_opened", type=Color, default='4012452351', help="opened paths")
        pars.add_argument("--color_closed", type=Color, default='2330080511', help="closed paths")
        pars.add_argument("--color_self_intersecting_paths", type=Color, default='2593756927', help="self-intersecting paths")
        pars.add_argument("--color_self_intersections", type=Color, default='6320383', help="self-intersecting path points")
        pars.add_argument("--color_global_intersections", type=Color, default='4239343359', help="global intersection points")
       
        #Style - Trimming Color
        pars.add_argument("--color_trimmed", type=Color, default='1923076095', help="trimmed lines")
        pars.add_argument("--color_combined", type=Color, default='3227634687', help="non-intersected lines")
        pars.add_argument("--color_nonintersected", type=Color, default='3045284607', help="non-intersected paths")


    def effect(self):

        so = self.options

        if so.break_apart is True and so.show_debug is True:
            self.msg("Warning: 'Break apart input' setting is enabled. Cannot check accordingly for relative, absolute or mixed paths for breaked elements (they are always absolute)!")
     
        #some constant stuff / styles
        relativePathStyle = {'stroke': str(so.color_relative), 'fill': 'none', 'stroke-width': so.strokewidth}
        absolutePathStyle = {'stroke': str(so.color_absolute), 'fill': 'none', 'stroke-width': so.strokewidth}
        mixedPathStyle = {'stroke': str(so.color_mixed), 'fill': 'none', 'stroke-width': so.strokewidth}
        polylinePathStyle = {'stroke': str(so.color_polyline), 'fill': 'none', 'stroke-width': so.strokewidth}
        bezierPathStyle = {'stroke': str(so.color_bezier), 'fill': 'none', 'stroke-width': so.strokewidth}
        openPathStyle = {'stroke': str(so.color_opened), 'fill': 'none', 'stroke-width': so.strokewidth}
        closedPathStyle = {'stroke': str(so.color_closed), 'fill': 'none', 'stroke-width': so.strokewidth}
        selfIntersectingPathStyle = {'stroke': str(so.color_self_intersecting_paths), 'fill': 'none', 'stroke-width': so.strokewidth}
        basicSubSplitLineStyle = {'stroke': str(so.color_subsplit), 'fill': 'none', 'stroke-width': so.strokewidth}

        #get all paths which are within selection or in document and generate sub split lines
        pathElements = self.get_path_elements()

        subSplitLineArray = []
        
        for pathElement in pathElements:
            originalPathId = pathElement.attrib["id"]
            path = pathElement.path.transform(pathElement.composed_transform())
            #path = pathElement.path
                
            '''
            check for relative or absolute paths
            '''
            isRelative = False
            isAbsolute = False
            isMixed = False
            relCmds = ['m', 'l', 'h', 'v', 'c', 's', 'q', 't', 'a', 'z']
            if any(relCmd in str(path) for relCmd in relCmds):
                isRelative = True
            if any(relCmd.upper() in str(path) for relCmd in relCmds):
                isAbsolute = True
            if isRelative is True and isAbsolute is True:
                isMixed = True
                isRelative = False
                isAbsolute = False
            if so.remove_absolute is True and isAbsolute is True:
                pathElement.delete()
                continue #skip this loop iteration
            if so.remove_relative is True and isRelative is True:
                pathElement.delete()
                continue #skip this loop iteration
            if so.remove_mixed is True and isMixed is True:
                pathElement.delete()
                continue #skip this loop iteration

            '''
            check for bezier or polyline paths
            '''
            isBezier = False
            if 'c' in str(path) or 'C' in str(path):
                isBezier = True
            if so.show_debug is True:
                self.msg("sub path in {} is bezier: {}".format(originalPathId, isBezier))                   
            if so.remove_beziers is True and isBezier is True:
                pathElement.delete()
                continue #skip this loop iteration
            if so.remove_polylines is True and isBezier is False:
                pathElement.delete()
                continue #skip this loop iteration


            '''
            check for closed or open paths
            '''
            isClosed = False
            raw = path.to_arrays()
            if raw[-1][0] == 'Z' or \
                (raw[-1][0] == 'L' and raw[0][1] == raw[-1][1]) or \
                (raw[-1][0] == 'C' and raw[0][1] == [raw[-1][1][-2], raw[-1][1][-1]]) \
                :  #if first is last point the path is also closed. The "Z" command is not required
                isClosed = True
            if so.remove_opened is True and isClosed is False:
                pathElement.delete()
                continue #skip this loop iteration
            if so.remove_closed is True and isClosed is True:
                pathElement.delete()
                continue #skip this loop iteration
  
            if so.draw_subsplit is True:
                subSplitLineGroup = pathElement.getparent().add(inkex.Group(id="{}-{}".format(idPrefix, originalPathId)))
           
            #get all sub paths for the path of the element
            subPaths, prev = [], 0
            for i in range(len(raw)): # Breaks compound paths into simple paths
                if raw[i][0] == 'M' and i != 0:
                    subPaths.append(raw[prev:i])
                    prev = i
            subPaths.append(raw[prev:])

            #now loop through all sub paths (and flatten if desired) to build up single lines
            for subPath in subPaths:                     
                subPathData = CubicSuperPath(subPath)

                #flatten bezier curves. If it was already a straight line do nothing! Otherwise we would split straight lines into a lot more straight lines
                if so.flattenbezier is True and isBezier is True:
                    bezier.cspsubdiv(subPathData, so.flatness) #modifies the path
                    flattenedpath = []
                    for seg in subPathData:
                        first = True
                        for csp in seg:
                            cmd = 'L'
                            if first:
                                cmd = 'M'
                            first = False
                            flattenedpath.append([cmd, [csp[1][0], csp[1][1]]])
                    #self.msg("flattened path = " + str(flattenedpath))
                    segs = list(CubicSuperPath(flattenedpath).to_segments())
                else:
                    segs = list(subPathData.to_segments())
                #segs = segs[::-1] #reverse the segments
                
                #build polylines from segment data
                subSplitLines = []
                for i in range(len(segs) - 1): #we could do the same routine to build up polylines using "for x, y in node.path.end_points". See "number nodes" extension
                    x1, y1, x2, y2 = self.line_from_segments(segs, i, so.decimals)
                    #self.msg("(y1 = {},y2 = {},x1 = {},x2 = {})".format(x1, y1, x2, y2))
                    subSplitId = "{}-{}_{}".format(idPrefix, originalPathId, i)
                    line = inkex.PathElement(id=subSplitId)
                    #apply line path with composed negative transform from parent element
                    line.path = [['M', [x1, y1]], ['L', [x2, y2]]]
                    if pathElement.getparent() != self.svg.root and pathElement.getparent() != None:
                        line.path = line.path.transform(-pathElement.getparent().composed_transform())
                    line.style = basicSubSplitLineStyle
                    line.attrib['originalPathId'] = originalPathId
                    line.attrib['originalPathIsRelative'] = str(isRelative)
                    line.attrib['originalPathIsAbsolute'] = str(isAbsolute)
                    line.attrib['originalPathIsMixed'] = str(isMixed)
                    line.attrib['originalPathIsBezier'] = str(isBezier)
                    line.attrib['originalPathIsClosed'] = str(isClosed)
                    line.attrib['originalPathStyle'] = str(pathElement.style)
                    subSplitLineArray.append(line)

                    if so.apply_style_to_subsplits is True:
                        if line.attrib['originalPathIsRelative'] == 'True':
                            if so.highlight_relative is True:
                                line.style = relativePathStyle
                  
                        if line.attrib['originalPathIsAbsolute'] == 'True':
                            if so.highlight_absolute is True:
                                line.style = absolutePathStyle
                             
                        if line.attrib['originalPathIsMixed'] == 'True':
                            if so.highlight_mixed is True:
                                line.style = mixedPathStyle
                        
                        if line.attrib['originalPathIsBezier'] == 'True':
                            if so.highlight_beziers is True:
                                line.style = bezierPathStyle
                        else:
                            if so.highlight_polylines is True:
                                line.style = polylinePathStyle
    
                        if line.attrib['originalPathIsClosed'] == 'True':
                            if so.highlight_closed is True:
                                line.style = closedPathStyle
                        else:
                            if so.highlight_opened is True:
                                line.style = openPathStyle

                    if so.draw_subsplit is True:
                        subSplitLineGroup.add(line)
                    subSplitLines.append([(x1, y1), (x2, y2)])
                    
                #check for self intersections using Bentley-Ottmann algorithm.
                isSelfIntersecting = False
                selfIntersectionPoints = isect_segments(subSplitLines, validate=True)
                if len(selfIntersectionPoints) > 0:
                    isSelfIntersecting = True
                    if so.show_debug is True:
                        self.msg("{} in {} intersects itself with {} intersections!".format(subSplitId, originalPathId, len(selfIntersectionPoints)))
                    if so.draw_subsplit is True:
                        if so.highlight_self_intersecting is True:
                            for subSplitLine in subSplitLineGroup:
                                subSplitLine.style = selfIntersectingPathStyle #adjusts line color
                        #delete cosmetic sub split lines if desired
                        if so.remove_self_intersecting:
                            subSplitLineGroup.delete()
                    if so.visualize_self_intersections is True: #draw points (circles)
                        self.visualize_self_intersections(pathElement, selfIntersectionPoints)

                    #delete self-intersecting sub split lines and orginal paths
                    if so.remove_self_intersecting:
                        subSplitLineArray = subSplitLineArray[:len(subSplitLineArray) - len(segs) - 1] #remove all last added lines
                        pathElement.delete() #and finally delete the orginal path
                        continue

            #adjust the style of original paths if desired. Has influence to the finally trimmed lines style results too!
            if so.removefillsetstroke is True:
                self.adjust_style(pathElement)

            #apply styles to original paths
            if isRelative is True:
                if so.highlight_relative is True:
                    pathElement.style = relativePathStyle
      
            if isAbsolute is True:
                if so.highlight_absolute is True:
                    pathElement.style = absolutePathStyle
                 
            if isMixed is True:
                if so.highlight_mixed is True:
                    pathElement.style = mixedPathStyle
            
            if isBezier is True:
                if so.highlight_beziers is True:
                    pathElement.style = bezierPathStyle
            else:
                if so.highlight_polylines is True:
                    pathElement.style = polylinePathStyle

            if isClosed is True:
                if so.highlight_closed is True:
                    pathElement.style = closedPathStyle
            else:
                if so.highlight_opened is True:
                    pathElement.style = openPathStyle

            if isSelfIntersecting is True:
                if so.highlight_self_intersecting is True:
                    pathElement.style = selfIntersectingPathStyle

            if so.draw_subsplit is True:
                if subSplitLineGroup is not None: #might get deleted before so we need to check this first
                    subSplitLineGroup = reversed(subSplitLineGroup) #reverse the order to match the original path segment placing

        if so.show_debug is True:
            self.msg("sub split line count: {}".format(len(subSplitLineArray)))   

        '''
        now we intersect the sub split lines to find the global intersection points using Bentley-Ottmann algorithm (contains self-intersections too!)
        '''
        if so.draw_trimmed is True:     
            try:        
                allSubSplitLineStrings = []
                for subSplitLine in subSplitLineArray:
                    csp = subSplitLine.path.to_arrays()
                    allSubSplitLineStrings.append([(csp[0][1][0], csp[0][1][1]), (csp[1][1][0], csp[1][1][1])])
                                
                globalIntersectionPoints = MultiPoint(isect_segments(allSubSplitLineStrings, validate=True))
       
                if so.show_debug is True:
                    self.msg("global intersection points count: {}".format(len(globalIntersectionPoints)))     
                if len(globalIntersectionPoints) > 0:
                    if so.visualize_global_intersections is True:
                        self.visualize_global_intersections(globalIntersectionPoints)
    
                    '''
                    now we trim the sub split lines at all calculated intersection points. 
                    We do this path by path to keep the logic between original paths, sub split lines and the final output
                    '''                            
                    allTrimGroups = [] #container to collect all trim groups for later on processing 
                    for subSplitIndex in range(len(subSplitLineArray)):
                        trimGroup = self.build_trim_line_group(subSplitLineArray, subSplitIndex, globalIntersectionPoints)
                        if trimGroup is not None:
                            if trimGroup not in allTrimGroups:
                                allTrimGroups.append(trimGroup)
                 
                    if so.show_debug is True: self.msg("trim groups count: {}".format(len(allTrimGroups)))
                    if len(allTrimGroups) == 0:
                        self.msg("You selected to draw trimmed lines but no intersections could be calculated.")
                         
                    #trim beziers - not working yet   
                    if so.bezier_trimming is True: self.trim_bezier(allTrimGroups)  
                   
                    #check for duplicate trim lines and delete them if desired
                    if so.remove_duplicates is True: self.remove_duplicates(allTrimGroups)
                                    
                    #glue together all non-intersected sub split lines to larger path structures again (cleaning up).
                    if so.combine_nonintersects is True: self. combine_nonintersects(allTrimGroups)

                    #clean original paths if selected. This option is explicitely independent from remove_open, remove_closed
                    if so.keep_original_after_trim is False:
                        for pathElement in pathElements:
                            pathElement.delete()
        
            except AssertionError as e:
                self.msg("Error calculating global intersections.\n\
See https://github.com/ideasman42/isect_segments-bentley_ottmann.\n\n\
You can try to fix this by:\n\
- reduce or raise the 'decimals' setting (default is 3 but try to set to 6 for example)\n\
- reduce or raise the 'flatness' setting (if quantization option is used at all; default is 0.100).")
            return

if __name__ == '__main__':
    ContourScannerAndTrimmer().run()