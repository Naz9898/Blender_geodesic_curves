import sys
import os
import bpy
import bmesh
import time
from mathutils import Vector
from mathutils.interpolate import poly_3d_calc

dir = os.path.dirname(bpy.context.space_data.text.filepath) #Get directory of the .py file
sys.path.append(dir) #Setting it as the python directory in the Blender Text editor 

import utils

class GeodesicCurveInfo:
    def __init__(self):
        self.points_bar  = [] #Control points in barycentric coordinates
        self.points_idx  = [] #Indices of control points in the mesh (subgroup of polygon_idx)
        self.polygon_idx = [] #Indices of control polygon in the mesh
        self.curve_idx   = [] #Indices of curve points in the mesh
        
curve_info = GeodesicCurveInfo() 

s = None #Socket
process = None #Subprocess for c++ engine

obj_name = None #Name of the current working object
    
#----------MOVE CONTROL POINT OPERATOR COMMUNICATION FUNCTIONS------------

#Return True if vert is a control point
def is_control(vert):
    return vert in curve_info.points_idx

#Update function for editing
#INPUT: index of selected control point and its new barycentric coordinate
#OUTPUT: new index of the same control point (since it changes after the mesh modification)
def update(bm, selectedVert, new_co):
    selected_idx = curve_info.points_idx.index(selectedVert)
    curve_info.points_bar[selected_idx] = new_co
    
    control_points, control_points_idx, curve = utils.get_all_data(s, obj_name, curve_info.points_bar)
    
    update_points(bm, obj_name, control_points, curve, control_points_idx)
    return curve_info.points_idx[selected_idx] 

#----------SPLINE DRAWING FUNCTION-----------------------

#Update coordinates of curve, add and delete points if needed
#INPUT: Bmesh (for intermediate calculations to avoid bmesh creation in each frame), curve info
def update_points(bm, obj_name, new_control, new_curve, new_points_idx):
    polygon_idx = curve_info.polygon_idx
    curve_idx = curve_info.curve_idx
    points_idx = curve_info.points_idx
    
    #Get sizes
    new_control_n = len(new_control)
    new_curve_n = len(new_curve)
    old_control_n = len(polygon_idx)
    old_curve_n = len(curve_idx)

    #Get mesh
    mesh = bpy.context.scene.objects[obj_name].data

    #update existing control points
    verts_control = []
    to_idx = new_control_n if new_control_n <= old_control_n else old_control_n
    bm.verts.ensure_lookup_table()
    for i in range(to_idx):
        bm.verts[polygon_idx[i]].co = new_control[i]
        verts_control.append(bm.verts[polygon_idx[i]])
        
    #update existing curve points
    verts_curve = []
    to_idx = new_curve_n if new_curve_n <= old_curve_n else old_curve_n
    for i in range(to_idx):
        bm.verts[curve_idx[i]].co = new_curve[i]
        verts_curve.append(bm.verts[curve_idx[i]])
    
    update_idx = False   
    #Delete vertices if needed
    to_delete = []
    if new_control_n <  old_control_n:
        update_idx = True
        for i in range(new_control_n, old_control_n):
            to_delete.append( bm.verts[polygon_idx[i]] )
    
    if new_curve_n <  old_curve_n:
        update_idx = True
        for i in range(new_curve_n, old_curve_n):
            to_delete.append( bm.verts[curve_idx[i]] ) 

    bmesh.ops.delete(bm, geom=to_delete)

    if new_control_n >  old_control_n:
        update_idx = True
        for i in range(old_control_n, new_control_n):
            verts_control.append( bm.verts.new( new_control[i] ) )
            bm.edges.new([verts_control[i-1], verts_control[i]]) 
            
    #add curve points if needed
    if new_curve_n >  old_curve_n:
        update_idx = True
        for i in range(old_curve_n, new_curve_n):
            verts_curve.append( bm.verts.new( new_curve[i] ) )
            bm.edges.new([verts_curve[i-1], verts_curve[i]]) 
     
    if update_idx: bm.verts.index_update()

    #Update indices
    curve_info.polygon_idx = [v.index for v in verts_control]
    curve_info.curve_idx = [v.index for v in verts_curve]
    curve_info.points_idx = [curve_info.polygon_idx[idx] for idx in new_points_idx]

    bm.to_mesh(mesh)
    
#Create curve and control polygon polylines
#INPUT: object name and curve info (barycentric coordinates of control points)
#OUTPUT: socket for the communication with c++ engine (needed for editing)
def draw_all(obj_name, curve_info):
    #Send control points to server
    s = utils.create_socket()
    control_points, control_points_idx, curve = utils.get_all_data(s, obj_name, curve_info.points_bar)
    curve_info.curve_idx  = draw_polyline(obj_name, curve)     
    curve_info.polygon_idx, curve_info.points_idx = draw_polyline(obj_name, control_points, control_points_idx)
    return s

#Draw single polyline, either control polygon or curve
#INPUT: obj_name and points. If is control polygon also the indices of the control points
#OUTPUT: indices of the vertices. If is control polygon also the indices of the control points
def draw_polyline(obj_name, points, control_points_idx = None):
    mesh = bpy.context.scene.objects[obj_name].data
    
    bm = bmesh.new()
    bm.from_mesh(mesh)

    verts = [bm.verts.new( points[0] )]    
    bm.verts.index_update()
    for i in range(1, len(points)):
        verts.append( bm.verts.new( points[i] ) )
        bm.edges.new([verts[i-1], verts[i]]) 
    bm.verts.index_update()   

    #Save new vertices indices
    vert_indices = [v.index for v in verts]
    
    # make the bmesh the object's mesh
    bm.to_mesh(mesh)  
    bm.free()  
    
    if control_points_idx:  
        control_indices = [vert_indices[idx] for idx in control_points_idx]
        return vert_indices, control_indices
    return vert_indices


class GeodesicCurve(bpy.types.Operator):
    #Geodesic curve
    bl_idname = "view3d.modal_operator_geocurve"
    bl_label = "Add geodesic curve"

    def modal(self, context, event):
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            return {'PASS_THROUGH'}
        elif event.type == 'LEFTMOUSE':
            if event.value == 'RELEASE':
                global obj_name, process, s
                hit_obj, loc, normal, face_index = utils.ray_cast(context, event)
                print(hit_obj)
                if hit_obj is not None:
                    if obj_name is None:
                        #If first click save object and triangulate
                        obj_name = hit_obj.name
                        utils.triangulate_object(bpy.context.scene.objects[obj_name])
                        hit_obj, loc, normal, face_index = utils.ray_cast(context, event)
                    if len(curve_info.points_bar) < 3:
                        #Save point in barycentric coordinates
                        mesh = hit_obj.data
                        poly = mesh.polygons[face_index]
                        corners = [mesh.vertices[vid].co for vid in poly.vertices]
                        bcoords = poly_3d_calc(corners, loc)
                        curve_info.points_bar.append( [face_index , bcoords[1:]] )

                    if len(curve_info.points_bar) == 3: 
                        curve_info.points_bar.append( curve_info.points_bar[-1] )
                        #Enough point, send to server
                        utils.save_file(hit_obj.data, dir + "\\bezier\\data\\tmp.obj")
                        process = utils.run_spline_server(dir)
                        
                        s = draw_all(obj_name, curve_info)


                return {'RUNNING_MODAL'}
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

class SelectPoint(bpy.types.Operator):
    bl_idname = "view3d.select_point"
    bl_label = "Select control point"

    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT')
        selected_idx = curve_info.points_idx[context.scene.to_select]
        bpy.context.scene.objects[obj_name].data.vertices[selected_idx].select = True
        bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}

def menu_func(self, context):
    self.layout.operator(GeodesicCurve.bl_idname, text="Geodesic Curve Operator")
    self.layout.operator(SelectPoint.bl_idname, text="Select control point")

# Register and add to the "view" menu (required to also use F3 search "Raycast View Modal Operator" for quick access)
def register():
    bpy.utils.register_class(GeodesicCurve)
    bpy.utils.register_class(SelectPoint)
    bpy.types.VIEW3D_MT_view.append(menu_func)

def unregister():
    bpy.utils.unregister_class(GeodesicCurve)
    bpy.utils.unregister_class(SelectPoint)
    bpy.types.VIEW3D_MT_view.remove(menu_func)

if __name__ == "__main__":
    register()
