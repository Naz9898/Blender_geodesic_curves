import sys
import os
import bpy
import bmesh
import numpy as np
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.interpolate import poly_3d_calc

dir = os.path.dirname(bpy.context.space_data.text.filepath) #Get directory of the .py file
sys.path.append(dir) #Setting it as the python directory in the Blender Text editor 

import utils

class GeodesicCurveInfo:
    def __init__(self):        
        self.points_bar  = [] #Control points in barycentric coordinates
        self.points_idx  = [] #Indices of control points in the mesh (subgroup of polygon_idx)
        
comm = utils.ServerCommunication()


#----------MOVE CONTROL POINT OPERATOR COMMUNICATION FUNCTIONS------------

#Control if requested object is the current working mesh, otherwise close it and create new process
def set_server(obj):
    if obj[utils.key_name] != comm.obj_key:
        #Close communication if other communication was active
        if comm.obj_key is not None:
            utils.close_spline_server(comm)
        utils.save_file(obj.data, dir + "\\bezier\\data\\tmp.obj")
        utils.run_spline_server(dir, comm)
        comm.obj_key = obj[utils.key_name]

#----------SPLINE DRAWING FUNCTION-----------------------

def draw_curve(obj, curve):
    #Create curve polygon
    curve_name = 'c'+str( len(utils.obj_curves_get(obj[utils.key_name]).value )) + obj[utils.key_name]
    
    curve_data = bpy.data.curves.new(name=curve_name, type='CURVE')  
    curve_data.dimensions = '3D'  

    obj_curve = bpy.data.objects.new(curve_name, curve_data)
    obj_curve[utils.key_name] = curve_name
    bpy.context.view_layer.active_layer_collection.collection.objects.link(obj_curve)

    curve_line = curve_data.splines.new('POLY')
    curve_line.points.add(len(curve)-1)
    for i, coord in enumerate(curve):
        x,y,z = coord
        curve_line.points[i].co = (x, y, z, 1)
    
    material = bpy.data.materials.new(curve_name+"polygon_material")
    material.diffuse_color = (0,0,1,1)
    curve_data.materials.append(material)
    curve_data.bevel_depth = 0.01
  
class GeodesicCurve(bpy.types.Operator):
    #Geodesic curve
    bl_idname = "view3d.modal_operator_geocurve"
    bl_label = "Add geodesic curve"
    bl_options = {'REGISTER','UNDO'}

    def __init__(self):
        self.points_bar = []
        self.obj_name = None
        
    def modal(self, context, event):
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            return {'PASS_THROUGH'}
        elif event.type == 'LEFTMOUSE':
            if event.value == 'RELEASE':
                hit_obj, loc, normal, face_index = utils.ray_cast(context, event)
                if hit_obj is not None:
                    obj = bpy.context.scene.objects[hit_obj.name]
                    key_name = utils.key_name 
                    if self.obj_name is None:
                        #If first click save object and triangulate
                        self.obj_name = obj.name
                        if key_name not in obj:
                            obj[key_name] = "o" + str(bpy.context.scene.total)
                            bpy.types.Scene.total += 1
                            utils.push_key(obj[key_name])
                            #Triangulate and recall the ray casting
                            utils.triangulate_object(obj)
                            hit_obj, loc, normal, face_index = utils.ray_cast(context, event)     
                             
                    if len(self.points_bar) < 3:
                        #Save point in barycentric coordinates
                        mesh = obj.data
                        poly = mesh.polygons[face_index]
                        corners = [mesh.vertices[vid].co for vid in poly.vertices]
                        bcoords = poly_3d_calc(corners, loc)
                        self.points_bar.append( [face_index , bcoords[1:]] )
                        
                    #Enough points, draw
                    if len(self.points_bar) == 3:
                        self.points_bar.append( self.points_bar[-1] )    
                        #Add key                    
                        """
                        if key_name not in obj:
                            obj[key_name] = "o" + str(bpy.context.scene.total)
                            bpy.types.Scene.total += 1
                            utils.push_key(obj[key_name])
                        """
                        #Create communication if necessary
                        self.report({'INFO'}, "Loading server")
                        set_server(obj)
                        self.report({'INFO'}, "Server loaded")
                        #Calculate curve and draw
                        #_, _, curve = utils.get_all_data(comm.s, obj, self.points_bar)
                        try: curve = utils.get_curve(comm.s, obj, self.points_bar)
                        except:
                            del obj[utils.key_name]
                            utils.reset_spline_server(comm)
                            self.report({'WARNING'}, "Geometry modified, curves on the objects invalidated") 
                            return {'CANCELLED'}
                        draw_curve(obj, curve)
                        #Push curve info
                        utils.add_curve(obj[key_name], self.points_bar)
                        return {'FINISHED'}

                return {'RUNNING_MODAL'}
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            if bpy.context.view_layer.objects.active: 
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.object.select_all(action='DESELECT')
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

     
#---------------TESTING.................................................

class PrintOperator(bpy.types.Operator):
    """Print status operator"""
    bl_idname = "view3d.print_operator"
    bl_label = "Print Operator"

    def execute(self, context):
        print("_________________")
        print("Total geo objects: ", bpy.context.scene.total)
        
        for item in bpy.context.scene.obj_curves:
            print(item.key, " ", len( item.value ), " curves" )
            for curve_idx, info in enumerate(item.value):
                print("\tcurve_idx: ", curve_idx)
                for p in info.points_bar:
                    print("\t\t", p.get())
        print("_________________\n\n")
        return {'FINISHED'}

        

def menu_func(self, context):
    self.layout.operator(GeodesicCurve.bl_idname, text="Geodesic Curve Operator")
    #TO DELETE
    self.layout.operator(PrintOperator.bl_idname, text="Print geodesic status")
    

# Register and add to the "view" menu (required to also use F3 search "Raycast View Modal Operator" for quick access)
def register():
    bpy.utils.register_class(GeodesicCurve)
    bpy.utils.register_class(PrintOperator)
    bpy.types.VIEW3D_MT_view.append(menu_func)

def unregister():
    bpy.utils.unregister_class(GeodesicCurve)
    bpy.types.VIEW3D_MT_view.remove(menu_func)

if __name__ == "__main__":
    register()
