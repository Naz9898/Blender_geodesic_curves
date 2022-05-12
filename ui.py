import sys
import os
import bpy

dir = os.path.dirname(bpy.context.space_data.text.filepath) #Get directory of the .blend file
sys.path.append(dir) #Setting it as the python directory in the Blender Text editor 

import spline
import move_point

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
        row.label(text="Hello world!", icon='WORLD_DATA')

        row = layout.row()
        row.operator("view3d.modal_operator_geocurve")
        
        row = layout.row()
        row.operator("view3d.move_control_point")
        
        row = layout.row()
        row.prop(context.scene, "to_select")
        
        row = layout.row()
        row.operator("view3d.select_point")

# Register and add to the "view" menu (required to also use F3 search "Raycast View Modal Operator" for quick access)
def register():
    bpy.utils.register_class(GeodesicPanel)
    spline.register()
    move_point.register()
    
    bpy.types.Scene.to_select = bpy.props.IntProperty(name="idx", default=0, min=0, max=3)

def unregister():
    bpy.utils.unregister_class(GeodesicPanel)
    spline.unregister()
    move_point.register()

if __name__ == "__main__":
    register()
