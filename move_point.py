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
import spline

#Returns index of the current selected vertex if it is a control point
#Returns -1 is more than one or no vertex is selected, or the selected vertex is not a control point 
def getSelectedVertex(context):
    obj = bpy.context.object
    #Get indices of selected vertices
    sel_idx = np.zeros(len(obj.data.vertices), dtype=bool)
    obj.data.vertices.foreach_get('select', sel_idx)
    selected = np.where(sel_idx==True)[0]
    #More than one or no vertex is selected
    if len(selected) != 1: 
        print("You can move only one vertex at a time!")
        return -1
    #Check if it is a control point
    if not spline.is_control(selected[0]):
        print("Not a control point!")
        return -1
    #Return index of selected vertex
    return selected[0]

class MovePointOperator(bpy.types.Operator):
    bl_idname = "view3d.move_control_point"
    bl_label = "Move control point of geodesic"
    selected_vert = -1
    bm = None
    
    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'
            
    def modal(self, context, event):
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            return {'PASS_THROUGH'}
        elif event.type == 'MOUSEMOVE':
            hit_obj, loc, normal, face_index = utils.ray_cast(context, event)
            if loc is not None: 
                #Calculate baricentryc coordinates
                mesh = hit_obj.data
                poly = mesh.polygons[face_index]
                corners = [mesh.vertices[vid].co for vid in poly.vertices]
                bcoords = poly_3d_calc(corners, loc)
                bar_co = [face_index, [bcoords[1], bcoords[2]]]
                #Update
                self.selected_vert = spline.update(self.bm, self.selected_vert, bar_co)
                
            return {'RUNNING_MODAL'}
        elif event.type in {'RIGHTMOUSE', 'LEFTMOUSE', 'ESC'}:
            #Finish operator
            bpy.context.object.data.vertices[self.selected_vert].select = False
            self.selected_vert = -1
            self.bm.free()
            return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            bpy.ops.object.mode_set(mode='OBJECT')
            self.selected_vert = getSelectedVertex(context)
            if self.selected_vert is None: 
                self.report({'WARNING'}, "Only one vertex must be selected, and it must be a control point")
                return {'CANCELLED'}
            bpy.context.object.data.vertices[self.selected_vert].select = True
            context.window_manager.modal_handler_add(self)
            #Create bmesh for updatejust once here
            self.bm = bmesh.new()
            self.bm.from_mesh(bpy.context.object.data)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

def menu_func(self, context):
    self.layout.operator(MovePointOperator.bl_idname, text="Move control point of geodesic")

# Register and add to the "view" menu (required to also use F3 search "Raycast View Modal Operator" for quick access)
def register():
    bpy.utils.register_class(MovePointOperator)
    bpy.types.VIEW3D_MT_view.append(menu_func)


def unregister():
    bpy.utils.unregister_class(MovePointOperator)
    bpy.types.VIEW3D_MT_view.remove(menu_func)


if __name__ == "__main__":
    register()
