#!/usr/bin/env python3
import sys
import os
import inkex
import tempfile
import subprocess
from subprocess import Popen, PIPE
from lxml import etree
from inkex import Transform

class PlyCutter(inkex.EffectExtension):
    
    def add_arguments(self, pars):
        pars.add_argument("--tab")    
        pars.add_argument("--infile")
        pars.add_argument("--resizetoimport", type=inkex.Boolean, default=True, help="Resize the canvas to the imported drawing's bounding box")
        pars.add_argument("--extraborder", type=float, default=0.0)
        pars.add_argument("--extraborder_units", default="mm")
        
        pars.add_argument("--thickness", type=float, default=6.000, help="Set the thickness of sheets to find.")
        pars.add_argument("--debug", type=inkex.Boolean, default=False, help="Turn on debugging") 
        pars.add_argument("--min_finger_width", type=float, default=3.000, help="Set minimum width for generated fingers.")
        pars.add_argument("--max_finger_width", type=float, default=5.000, help="Set maximum width for generated fingers.")
        pars.add_argument("--support_radius", type=float, default=12.000, help="Set maximum range for generating material on a sheet where neither surface is visible")
        pars.add_argument("--final_dilation", default=0.05, type=float, help="Final dilation (laser cutter kerf compensation)")
        pars.add_argument("--random_seed", type=int, default=42, help="Random seed for pseudo-random heuristics")       

    def effect(self):
        stl_input = self.options.infile
        if not os.path.exists(stl_input):
            inkex.utils.debug("The input file does not exist. Please select a proper file and try again.")
            exit(1)

        # Prepare output
        basename =  os.path.splitext(os.path.basename(stl_input))[0]
        svg_output = os.path.join(tempfile.gettempdir(), basename + ".svg")

        # Clean up possibly previously generated output file from plycutter
        if os.path.exists(svg_output):
            try:
                os.remove(svg_output)
            except OSError as e: 
                inkex.utils.debug("Error while deleting previously generated output file " + stl_input)

        # Run PlyCutter
        plycutter_cmd = "plycutter "
        plycutter_cmd += "--thickness " + str(self.options.thickness) + " "
        if self.options.debug == True: plycutter_cmd += "--debug "
        plycutter_cmd += "--min_finger_width " + str(self.options.min_finger_width) + " "
        plycutter_cmd += "--max_finger_width " + str(self.options.max_finger_width) + " "
        plycutter_cmd += "--support_radius " + str(self.options.support_radius) + " "
        plycutter_cmd += "--final_dilation " + str(self.options.final_dilation) + " "
        plycutter_cmd += "--random_seed " + str(self.options.random_seed) + " "
        plycutter_cmd += "--format svg " #static
        plycutter_cmd += "-o \"" + svg_output + "\" "
        plycutter_cmd += "\"" + stl_input + "\""
        
        #print command 
        #inkex.utils.debug(plycutter_cmd)
    
        #create a new env for subprocess which does not contain extensions dir because there's a collision with "rtree.py"
        pypath = ''
        for d in sys.path:
            if d != '/usr/share/inkscape/extensions':
                pypath = pypath + d + ';'
        neutral_env = os.environ.copy()
        neutral_env['PYTHONPATH'] = pypath

        p = Popen(plycutter_cmd, shell=True, stdout=PIPE, stderr=PIPE, env=neutral_env)
        stdout, stderr = p.communicate()

        p.wait()
        if p.returncode != 0: 
           inkex.utils.debug("PlyCutter failed: %d %s %s" % (p.returncode, 
                str(stdout).replace('\\n', '\n').replace('\\t', '\t'), 
                str(stderr).replace('\\n', '\n').replace('\\t', '\t'))
                )
           exit(1)
        elif self.options.debug is True: 
           inkex.utils.debug("PlyCutter debug output: %d %s %s" % (p.returncode, 
                str(stdout).replace('\\n', '\n').replace('\\t', '\t'), 
                str(stderr).replace('\\n', '\n').replace('\\t', '\t'))
                )

        # Write the generated SVG into InkScape's canvas
        try:
            stream = open(svg_output, 'r')
        except FileNotFoundError as e:
            inkex.utils.debug("There was no SVG output generated by PlyCutter. Please check your model file.")
            exit(1)
        p = etree.XMLParser(huge_tree=True)
        doc = etree.parse(stream, parser=etree.XMLParser(huge_tree=True)).getroot()
        stream.close()
        
        g = inkex.Group(id=self.svg.get_unique_id("plycutter-"))
        g.insert(0, inkex.Desc("Imported file: {}".format(self.options.infile)))
        self.svg.get_current_layer().add(g)
        for element in doc.iter("{http://www.w3.org/2000/svg}path"):
            g.append(element)
            
        #Adjust viewport and width/height to have the import at the center of the canvas
        if self.options.resizetoimport:
            bbox = g.bounding_box() #does not work correctly if only 2 objects are inside (strangely). need at least 3 (e.g. one svg:desc and 2 svg:path elements)
            if bbox is not None:
                root = self.svg.getElement('//svg:svg');
                offset = self.svg.unittouu(str(self.options.extraborder) + self.options.extraborder_units)
                root.set('viewBox', '%f %f %f %f' % (bbox.left - offset, bbox.top - offset, bbox.width + 2 * offset, bbox.height + 2 * offset))
                root.set('width', bbox.width + 2 * offset)
                root.set('height', bbox.height + 2 * offset)
            else:
                self.msg("Error resizing to bounding box.")

if __name__ == '__main__':
    PlyCutter().run()