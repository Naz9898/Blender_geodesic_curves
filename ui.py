import sys
import os
import bpy
from bpy.app.handlers import persistent

dir = os.path.dirname(bpy.context.space_data.text.filepath) #Get directory of the .blend file
sys.path.append(dir) #Setting it as the python directory in the Blender Text editor 

import spline
import edit
import utils

class GeodesicPanel(bpy.types.Panel):
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

@persistent
def geometry_check(scene, depsgraph):
    for obj in depsgraph.updates:
        if utils.key_name in obj.id and obj.id[utils.key_name][0] == 'o' and obj.is_updated_geometry:
            
            print(obj.id.name + " geometry updated!, key: ", obj.id[utils.key_name])
            del bpy.context.scene.objects[obj.id.name][utils.key_name]

# Register and add to the "view" menu (required to also use F3 search "Raycast View Modal Operator" for quick access)
def register():
    bpy.utils.register_class(GeodesicPanel)
    spline.register()
    edit.register()
    
    #bpy.app.handlers.depsgraph_update_post.append(geometry_check)
def unregister():
    bpy.utils.unregister_class(GeodesicPanel)
    spline.unregister()
    edit.unregister()

if __name__ == "__main__":
    register()
