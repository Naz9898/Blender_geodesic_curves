import sys
import os
import bpy
from bpy.app.handlers import persistent

dir = os.path.dirname(bpy.context.space_data.text.filepath) #Get directory of the .blend file
sys.path.append(dir) #Setting it as the python directory in the Blender Text editor 

import spline
import edit
import utils

class MainPanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Geodesic"

class GeodesicPanel(MainPanel, bpy.types.Panel):
    """Creates a Panel in the Object properties window"""
    bl_label = "Geodesic Panel"
    bl_idname = "OBJECT_PT_geodesic"
    bl_space_type = "VIEW_3D"  
    bl_region_type = "UI"
    bl_category = "Geodesic"

    def draw(self, context):
        layout = self.layout

        row = layout.row()
        row.operator("view3d.modal_operator_geocurve")
        
        row = layout.row()
        row.operator("view3d.edit_curve")
        

class PropertiesPanel(MainPanel, bpy.types.Panel):
    bl_parent_id = "OBJECT_PT_geodesic"
    bl_label = "Properties Panel"
    bl_idname = "PROP_PT_geodesic"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.prop(context.scene, 'decastel_jau')
        
        row = layout.row()
        row.prop(context.scene, 'subdivisions')

@persistent
def remove_tan(scene):    
    tan = utils.getObjByKey("t")
    if tan is not None and not edit.is_running: 
        bpy.data.objects.remove(tan, do_unlink=True)
    
# Register and add to the "view" menu (required to also use F3 search "Raycast View Modal Operator" for quick access)
def register():
    bpy.utils.register_class(GeodesicPanel)
    bpy.utils.register_class(PropertiesPanel)
    spline.register()
    edit.register()
    
    bpy.app.handlers.undo_post.append(remove_tan)
    bpy.app.handlers.redo_post.append(remove_tan)
def unregister():
    bpy.utils.unregister_class(GeodesicPanel)
    bpy.utils.unregister_class(PropertiesPanel)
    spline.unregister()
    edit.unregister()

if __name__ == "__main__":
    register()
