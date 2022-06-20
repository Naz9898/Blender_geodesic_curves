import sys
import os
import bpy
import numpy as np

from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.interpolate import poly_3d_calc

dir = os.path.dirname(bpy.context.space_data.text.filepath) #Get directory of the .py file
sys.path.append(dir) #Setting it as the python directory in the Blender Text editor

import utils
import spline

def create_poly(obj_name, color, bevel = 0.01):
    data = bpy.data.curves.new(name=obj_name+'_data', type='CURVE')  
    data.dimensions = '3D'  

    obj_tan = bpy.data.objects.new(obj_name, data)
    obj_tan[utils.key_name] = "t"  
    bpy.context.view_layer.active_layer_collection.collection.objects.link(obj_tan)

    data.splines.new('POLY')

    material = bpy.data.materials.new("polygon_material")
    material.diffuse_color = color
    data.materials.append(material)
    data.bevel_depth = bevel
    return obj_tan

def rotate_tan(p0, p1, p2, end):
    send = "r" + str(end) + "\n"
    send += utils.pbar2str( p0 ) 
    send += utils.pbar2str( p1 ) 
    send += utils.pbar2str( p2 ) 
    try: spline.comm.s.sendall(send.encode())
    except: return False
    new_control = spline.comm.s.recv(2048).decode().splitlines()[0].split()
    return [int(new_control[0]), [float(new_control[1]), float(new_control[2])]]

def print_debug():
    print("_________________")
    print("Total geo objects: ", bpy.context.scene.total)
    
    for item in bpy.context.scene.obj_curves:
        print(item.key, " ", len( item.value ), " curves" )
        for curve_idx, info in enumerate(item.value):
            print("\tcurve_idx: ", curve_idx)
            for p in info.points_bar:
                print("\t\t", p.get())
            print("is_closed: ", info.is_closed)
    print("_________________\n\n")
    return 

bpy.types.Scene.curr_idx  = bpy.props.IntProperty(default=-1) # For editing
is_running = False

class EditCurveOperator(bpy.types.Operator):
    """Pick control point"""
    bl_idname = "view3d.edit_curve"
    bl_label = "Edit bezier spline"
    bl_options = {'REGISTER'}
    
    def __init__(self):
        self.curve_key = None #For restoring on undo
        curve_item = None
        points_bar = None
        target = None
        curve = None
        tan = None
        
        self.clicking = False
        self.drag     = False
        
        self.split_mode = False
        self.t0 = 0.1

    def modal(self, context, event):
        global is_running
        #Scene navigation, zoom pan and rotate camera
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and not event.ctrl:
            return {'PASS_THROUGH'} # allow navigation
        elif event.type == 'Z' and event.value == 'RELEASE' and event.ctrl:
            #Redo
            if event.shift: 
                try: bpy.ops.ed.redo()
                except: return {'RUNNING_MODAL'}   
            #Undo
            else: bpy.ops.ed.undo()
            tan = utils.getObjByKey("t")
            if tan is None:
                self.report({'WARNING'}, "Exiting editing mode")
                is_running = False
                return {'FINISHED'}
            self.init_refs()
            bpy.context.view_layer.objects.active = self.tan
            bpy.ops.object.mode_set(mode = 'EDIT') 
            if not self.draw_curve(): return {'FINISHED'} 
            if not self.draw_tan(context):   return {'FINISHED'}
        #Exit
        elif event.type == 'ESC':
            bpy.data.objects.remove(self.tan, do_unlink=True)
            is_running = False
            return {'FINISHED'}

        #Split mode functions
        elif self.split_mode:
            if event.type == 'WHEELUPMOUSE' and event.ctrl:
                n_splines = (len(self.points_bar) - 1)/3
                if self.t0 < n_splines: 
                    self.t0 = self.t0 + 0.1
                    self.t0 = round(self.t0,1)
                if not self.draw_t0(): return {'FINISHED'}
            elif event.type == 'WHEELDOWNMOUSE' and event.ctrl:
                if self.t0 > 0: 
                    self.t0 = self.t0 - 0.1
                    self.t0 = round(self.t0,1)
                if not self.draw_t0(): return {'FINISHED'}
            elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                if not self.split(context): return {'FINISHED'} 
                self.split_mode = False
                self.report({'INFO'}, "Splitted")
                if not self.draw_curve(): return {'FINISHED'}
                if not self.draw_tan(context): return {'FINISHED'} 
                self.push_state()
            elif event.type== 'S' and event.value== 'RELEASE':
                self.split_mode = False
                context.scene.curr_idx = 0
                if not self.draw_tan(context): return {'FINISHED'}
                self.report({'INFO'}, "Exit split mode")
            return {'RUNNING_MODAL'}
        #Normal editing operations       
        elif event.type == 'LEFTMOUSE':
            if event.value == 'PRESS': self.clicking = True
            if event.value == 'RELEASE':
                self.clicking = False
                if self.drag:
                    self.drag = False
                    self.push_state()
                    return {'RUNNING_MODAL'}
                #If was not dragging pick
                hit_obj, loc, normal, face_index = utils.ray_cast(context, event)
                if not hit_obj: return {'RUNNING_MODAL'}
                hit_obj = bpy.context.scene.objects[hit_obj.name] #Get evaluated object
                if utils.key_name in hit_obj and hit_obj[utils.key_name] == self.target[utils.key_name]:
                    #Correct object hit
                    coord = event.mouse_region_x, event.mouse_region_y
                    if not self.pick(context, coord): return {'FINISHED'}  
                    if not self.draw_tan(context): return {'FINISHED'}
                    self.push_state()
            return {'RUNNING_MODAL'}
        #Add bezier segment
        elif event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
            hit_obj, loc, normal, face_index = utils.ray_cast(context, event)
            if not hit_obj: return {'RUNNING_MODAL'}
            hit_obj = bpy.context.scene.objects[hit_obj.name]
            if utils.key_name in hit_obj and hit_obj[utils.key_name] == self.target[utils.key_name]:

                coord = event.mouse_region_x, event.mouse_region_y
                if self.curve_item.is_closed: return {'RUNNING_MODAL'}
                #Get barycentric coords
                mesh = self.target.data
                poly = mesh.polygons[face_index]
                corners = [mesh.vertices[vid].co for vid in poly.vertices]
                bcoords = poly_3d_calc(corners, loc)
                new_point = [face_index , bcoords[1:]]
                #Add control point
                try: 
                    utils.send_tan_extension(spline.comm.s, self.points_bar[-2], self.points_bar[-1])
                    new_control = spline.comm.s.recv(2048).decode().splitlines()[0].split()
                except:
                    self.invalidate_target()
                    return {'FINISHED'}
                new_bar = [int(new_control[0]), [float(new_control[1]), float(new_control[2])]]
                new_points_bar = [self.points_bar[-1].get(), new_bar, new_point, new_point]
                
                if not self.add_curve(context, new_points_bar): return {'FINISHED'} 
                if not self.draw_tan(context): return {'FINISHED'}
                self.push_state()
            return {'RUNNING_MODAL'}
        #Drag
        elif event.type == 'MOUSEMOVE' and self.clicking:
            if not self.drag:
                self.drag = True
            hit_obj, loc, normal, face_index = utils.ray_cast(context, event)
            if not hit_obj: return {'RUNNING_MODAL'}
            hit_obj = bpy.context.scene.objects[hit_obj.name]
            if utils.key_name in hit_obj and hit_obj[utils.key_name] == self.target[utils.key_name]:
                idx = context.scene.curr_idx
                #Calculate barycentric coords
                mesh = self.target.data
                poly = mesh.polygons[face_index]
                corners = [mesh.vertices[vid].co for vid in poly.vertices]
                bcoords = poly_3d_calc(corners, loc)
                new_point = [face_index , bcoords[1:]]
                #Update point
                utils.update_point(self.points_bar[idx], new_point)
                            
                #Closed curve cases
                if self.curve_item.is_closed and idx == 0:
                    utils.update_point(self.points_bar[idx-1], new_point)
                    
                if self.curve_item.is_closed and idx == len(self.points_bar) - 1:
                    utils.update_point(self.points_bar[0], new_point)
                     
                #Draw
                if not self.draw_curve(): return {'FINISHED'}
                #Update tangents
                if self.curve_item.smooth:
                    idx = context.scene.curr_idx
                    if idx % 3 == 1 and (idx > 1 or self.curve_item.is_closed):
                        p1 = idx-2
                        p2 = idx-1
                        p3 = idx
                        if idx == 1: p1 = len(self.points_bar) -2 
                        new_point = rotate_tan(self.points_bar[p1].get(), self.points_bar[p2].get(), self.points_bar[p3].get(), 0)
                        if not new_point:
                            self.invalidate_target()
                            return {'FINISHED'}
                        utils.update_point(self.points_bar[p1], new_point)
                        
                    if idx%3==2 and (idx<len(self.points_bar)-2 or self.curve_item.is_closed):
                        p1 = idx
                        p2 = idx+1
                        p3 = idx+2
                        if idx == len(self.points_bar) -2: p3 = 1
                        new_point = rotate_tan(self.points_bar[p1].get(), self.points_bar[p2].get(), self.points_bar[p3].get(), 1)
                        if not new_point:
                            self.invalidate_target()
                            return {'FINISHED'}
                        utils.update_point(self.points_bar[p3], new_point)
                     
                if not self.draw_tan(context): return {'FINISHED'}
            return {'RUNNING_MODAL'}
        #Sharp/smooth tangents switch
        elif event.type== 'T' and event.value== 'RELEASE':
            if self.curve_item.smooth:
                self.curve_item.smooth = False
                self.report({'INFO'}, "Sharp tangents")
            else: 
                self.curve_item.smooth = True
                self.report({'INFO'}, "Smooth tangents")
            return {'RUNNING_MODAL'}
        #Split
        elif event.type== 'S' and event.value== 'RELEASE':
            self.split_mode = True
            self.report({'INFO'}, "Enter split mode")
        
            self.tan.data.splines.clear( )
            poly = self.tan.data.splines.new('POLY')
            bpy.context.view_layer.objects.active = self.tan
            bpy.ops.object.mode_set(mode = 'EDIT') 
            self.tan.data.splines[0].points[0].select = True 
            if not self.draw_t0(): return {'FINISHED'}
            return {'RUNNING_MODAL'}
            
        #Close spline
        elif event.type == 'C' and event.value == 'RELEASE':
            #print("Closed test: ", self.curve_item.is_closed)
            #self.push_state()
            if not self.curve_item.is_closed: 
                
                #Close spline
                start = self.points_bar[0].get()
                end   = self.points_bar[-1].get()
                #Check if already overlapping 
                if start[0] != end[0] or start[1][0] != end[1][0] or start[1][1] != end[1][1]:  
                    if self.curve_item.smooth:
                        #Extension 1
                        try:
                            utils.send_tan_extension(spline.comm.s, self.points_bar[1], self.points_bar[0])
                            new_control = spline.comm.s.recv(2048).decode().splitlines()[0].split()
                        except:
                            self.invalidate_target()
                            return {'FINISHED'}
                        new_bar_1 = [int(new_control[0]), [float(new_control[1]), float(new_control[2])]]
                        #extension 2
                        try:
                            utils.send_tan_extension(spline.comm.s, self.points_bar[-2], self.points_bar[-1])
                            new_control_2 = spline.comm.s.recv(2048).decode().splitlines()[0].split()
                        except:
                            self.invalidate_target()
                            return {'FINISHED'}
                        new_bar_2 = [int(new_control_2[0]), [float(new_control_2[1]), float(new_control_2[2])]]
                        new_points_bar = [self.points_bar[-1].get(), new_bar_2, new_bar_1, self.points_bar[0].get()]
                    else: new_points_bar = [self.points_bar[-1].get(), self.points_bar[-1].get(), self.points_bar[0].get(), self.points_bar[0].get()]
                    if not self.add_curve(context, new_points_bar): return {'FINISHED'}
                self.curve_item.is_closed = True
                self.report({'INFO'}, "Spline closed")
            else: 
                self.curve_item.is_closed = False
                self.report({'INFO'}, "Spline opened")
            self.push_state()
            return {'RUNNING_MODAL'}
        #Delete
        elif event.type == 'X' and event.value == 'RELEASE':
            #self.push_state()
            self.delete_segment(context)
            if not self.draw_curve(): return {'FINISHED'} 
            if not self.draw_tan(context):   return {'FINISHED'}
            self.push_state()
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        global is_running
        context.scene.curr_idx = 0
        
        if context.space_data.type == 'VIEW_3D':
            obj = bpy.context.view_layer.objects.active
            if obj is None or utils.key_name not in obj or obj[utils.key_name][0] != 'c':
                self.report({'WARNING'}, "Active object must be curve to edit")
                return {'CANCELLED'}
            
            self.curve_key = obj[utils.key_name] 
            if not self.init_refs(): return {'CANCELLED'}
            bpy.ops.object.mode_set(mode='OBJECT') 
            bpy.ops.object.select_all(action='DESELECT')
            spline.set_server(self.target)
            if not self.draw_curve(): return {'CANCELLED'}
            if not self.draw_tan(context): return {'CANCELLED'} 
            self.push_state()
            is_running = True
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}
    
    def init_refs(self):
        #Set curve pointer
        self.curve = utils.getObjByKey(self.curve_key)
        #Set tan pointer, create if necessary
        tan = utils.getObjByKey("t")
        if tan is None:
            tan = create_poly("tangent_tmp", (1,0,0,1), self.curve.data.bevel_depth)    
        self.tan = tan
        geo_key = self.curve[utils.key_name]
        #Set target pointer
        idx = geo_key.find('o')
        curve_idx = int(geo_key[1:idx])
        obj_key = geo_key[idx:]
        target = utils.getObjByKey(obj_key)
        if target is None:
            self.report({'WARNING'}, "Curve invalidated since the geometry has been modified")
            return False 
        self.target = target
        #Set curve info
        self.curve_item = utils.obj_curves_get(obj_key).value[curve_idx]
        self.points_bar = self.curve_item.points_bar
        return True
    
    def push_state(self):
        bpy.context.view_layer.objects.active = None
        bpy.ops.ed.undo_push()
        bpy.context.view_layer.objects.active = self.tan
    
    def eval_point(self):
        n_splines = (len(self.points_bar) - 1)/3
        anchor = int(self.t0) * 3
        t0_loc = self.t0 - int(self.t0)
        if anchor == n_splines*3: 
            anchor -= 3
            t0_loc = 1
        #print("Anchor: ", anchor, " t0: ", t0_loc)
        
        send = "p\n"+str(t0_loc)+"\n"
        for i in range(4): send += utils.pbar2str( self.points_bar[anchor + i].get() ) 
        spline.comm.s.sendall(send.encode())
        new_control = spline.comm.s.recv(2048).decode().splitlines()[0].split()
        return [int(new_control[0]), float(new_control[1]), float(new_control[2])]
    
    def draw_t0(self):
        #Set coord
        p_bar = []
        try: 
            p_bar.append( self.eval_point() ) 
            utils.convert_coords(self.target, p_bar)
        except:
            self.invalidate_target()
            return False
        
        x, y, z = p_bar[0]
        self.tan.data.splines[0].points[0].co = (x, y, z, 1.0) 
        return True
    
    def draw_pickable(self, context):
        pickable = range(0, len(self.points_bar), 3) 
        #Closed curve case
        if self.curve_item.is_closed and (context.scene.curr_idx == 0 or context.scene.curr_idx == len(self.points_bar)-1): 
            pickable = range(3, len(self.points_bar)-1, 3)
        for i in pickable:
            if i !=  context.scene.curr_idx: 
                #Overlapping check
                if i > context.scene.curr_idx:
                    p1 = self.points_bar[context.scene.curr_idx].get()
                    p2 = self.points_bar[i].get()
                    if p1[0] == p2[0] and p1[1][0] == p2[1][0] and p1[1][1] == p2[1][1]: continue  
                #Calculate 3d point
                p_bar = self.points_bar[i].get()
                p = [[p_bar[0], p_bar[1][0], p_bar[1][1]]]
                utils.convert_coords(self.target, p)
                #Add to object
                poly = self.tan.data.splines.new('POLY')
                poly.points.add( 1 )
                x,y,z = p[0]
                poly.points[0].co = (x, y, z, 1)
                poly.points[1].co = (x, y, z, 1)        
        
        
    def pick(self, context, point_2d):
        obj = self.target
        points_bar = self.points_bar
        
        region = context.region
        region_3d = context.space_data.region_3d
        
        anchor_idx = context.scene.curr_idx #Closest anchor point
        if anchor_idx % 3 == 1: anchor_idx -= 1
        if anchor_idx % 3 == 2: anchor_idx += 1
        tan_points = []
        if anchor_idx > 0: tan_points.append(anchor_idx - 1)
        if anchor_idx < len(points_bar) - 1: tan_points.append(anchor_idx + 1)
        if self.curve_item.is_closed and anchor_idx == 0: tan_points.append(len(self.points_bar)-2)
        if self.curve_item.is_closed and anchor_idx == len(self.points_bar)-1: tan_points.append(1)
        
        best_idx = -1
        best_dist = -1
        for idx, p_item in enumerate( points_bar ):
            if idx % 3 == 0 or idx in tan_points:
                #Convert barycentric coord in 3D
                curr_p = [[p_item.get()[0], p_item.get()[1][0], p_item.get()[1][1]]]
                try: utils.convert_coords(obj, curr_p)
                except:
                    self.invalidate_target()
                    return False
                #Project on screen
                co_2d = view3d_utils.location_3d_to_region_2d(region, region_3d, curr_p[0])
                dist = np.sqrt((point_2d[0]-co_2d[0])**2 + (point_2d[1]-co_2d[1])**2)
                #Occlusion check
                face_idx = p_item.get()[0]
                hit_obj, _, _, hit_face = utils.ray_cast(context, None, co_2d)
                if hit_obj and utils.key_name in hit_obj:
                    if hit_obj[utils.key_name] == obj[utils.key_name] and hit_face == face_idx:
                        #Not occluded, can be selected
                        if best_idx == -1 or dist <= best_dist:
                            best_idx = idx
                            best_dist = dist
        if best_idx != context.scene.curr_idx: 
            if best_dist < 60: context.scene.curr_idx =  best_idx
            else: context.scene.curr_idx = 0
        
        return True
    
    def split(self, context):
        #Send request
        old_len = len(self.points_bar)
        anchor = int(self.t0) * 3
        t0_loc = self.t0 - int(self.t0)
        if anchor == len(self.points_bar) - 1: 
            anchor -= 3
            t0_loc = 1 
        points_bar = []
        for i in range(4): points_bar.append( self.points_bar[anchor + i].get() )
        try: utils.send_split(spline.comm.s, points_bar, t0_loc)
        except:
            self.invalidate_target()
            return False
        new_points, _ = utils.recv_points(spline.comm.s)
        to_push = [p.get() for p in self.points_bar[-3:]]
        #Add new points
        for p in to_push: utils.add_point(self.points_bar, p) 
        #Move points
        if old_len - anchor > 7:
            from_idx = len(self.points_bar) - 4
            to_idx = anchor + 6
            for i in range(from_idx, anchor + 6, -1): 
                utils.update_point(self.points_bar[i], self.points_bar[i-3].get())
        
        #Copy new points
        for i in range( len(new_points) ):
            p_bar = [new_points[i][0], [new_points[i][1], new_points[i][2]]]
            utils.update_point(self.points_bar[anchor + i], p_bar)
            
        context.scene.curr_idx = anchor + 3
        return True
    
    def draw_curve(self):
        poly = self.curve.data.splines.new('POLY')
        for i in range(0, len(self.points_bar) - 1, 3):
            segment = []
            for j in range(4): segment.append(self.points_bar[i+j].get())
            try: curve_seg = utils.get_curve(spline.comm.s, self.target, segment)
            except:
                self.invalidate_target()
                return False

            old_len = len( poly.points )
            poly.points.add( len(curve_seg)-1 ) 
            #If first segment add first point
            if i == 0: 
                x,y,z = curve_seg[0]
                poly.points[0].co = (x, y, z, 1) 
            for i, coord in enumerate(curve_seg[1:]):
                x,y,z = coord
                poly.points[i + old_len].co = (x, y, z, 1)
        self.curve.data.splines.remove( self.curve.data.splines[0] )
        return True
    
    def draw_tan(self, context):
        self.tan.data.splines.clear()
        
        tan_1 = []
        tan_2 = []
        
        idx = context.scene.curr_idx #Closest anchor point
        if idx % 3 == 1: idx -= 1
        if idx % 3 == 2: idx += 1
        
        poly = None
        if idx > 0 or self.curve_item.is_closed:
            p1 = idx-1
            p2 = idx
            if idx == 0: p1 = len(self.points_bar) -2
            try: tan_1 = utils.get_straight_path(spline.comm.s, self.target, self.points_bar[p1].get(), self.points_bar[p2].get())
            except:
                self.invalidate_target()
                return False 
            utils.convert_coords(self.target, tan_1)
            poly = self.tan.data.splines.new('POLY')
            poly.points.add(len(tan_1)-1)
            for i, coord in enumerate(tan_1):
                x,y,z = coord
                poly.points[i].co = (x, y, z, 1)
                poly.points[i].hide = True
            poly.points[0].hide = False
            poly.points[-1].hide = False
        if idx < len(self.points_bar) - 2 or self.curve_item.is_closed:
            p1 = idx
            p2 = idx+1
            if idx == len(self.points_bar) -1: p2 = 1
            try: tan_2 = utils.get_straight_path(spline.comm.s, self.target, self.points_bar[p1].get(), self.points_bar[p2].get())
            except:
                self.invalidate_target()
                return False
            utils.convert_coords(self.target, tan_2)
            old_len = 0
            from_idx = 1
            if poly is None: 
                poly = self.tan.data.splines.new('POLY')
                from_idx = 0
            else: old_len = len(poly.points) 
            poly.points.add(len(tan_2)-1)
            for i, coord in enumerate(tan_2[from_idx:]):
                x,y,z = coord
                poly.points[old_len + i].co = (x, y, z, 1)
                poly.points[old_len + i].hide = True
            if len(tan_1) == 0: poly.points[0].hide = False
            poly.points[-1].hide = False
        #Select vert   
        bpy.context.view_layer.objects.active = self.tan
        bpy.ops.object.mode_set(mode = 'EDIT')          
        if context.scene.curr_idx % 3 == 2: to_select = 0
        if context.scene.curr_idx % 3 == 1: to_select = len(poly.points) - 1
        if context.scene.curr_idx % 3 == 0:
            if   len(tan_1) == 0: to_select = 0
            else: to_select = len(tan_1) - 1   
        self.tan.data.splines[0].points[to_select].select = True  
        #Draw other pickable objects first
        try: self.draw_pickable(context)
        except:
            self.invalidate_target()
            return False
        
        return True
    
    def delete_segment(self, context):
        if len(self.points_bar) == 4: 
            self.report({'WARNING'}, "Only one segment present") 
            return
        idx = context.scene.curr_idx #Closest anchor point
        if idx % 3 == 1: idx -= 1
        if idx % 3 == 2: idx += 1
        
        if idx == 0: idx = 1
        if idx == len(self.points_bar) - 1: 
            idx -= 1
            context.scene.curr_idx -= 3
        
        self.points_bar.remove(idx + 1)
        self.points_bar.remove(idx)
        self.points_bar.remove(idx -1)
        
        if context.scene.curr_idx > len(self.points_bar) - 1:
            context.scene.curr_idx = len(self.points_bar) - 1
        
    def add_curve(self, context, new_points_bar):
        utils.add_point(self.points_bar, new_points_bar[1])
        utils.add_point(self.points_bar, new_points_bar[2])
        utils.add_point(self.points_bar, new_points_bar[3])
        #Calculate additional curve and draw
        try: curve = utils.get_curve(spline.comm.s, self.target, new_points_bar)
        except:
            self.invalidate_target()
            return False
        poly_line = self.curve.data.splines[0]
        old_len_curve = len( poly_line.points )
        poly_line.points.add( len(curve)-1 )
        for i, coord in enumerate(curve[1:]):
            x,y,z = coord
            poly_line.points[i + old_len_curve].co = (x, y, z, 1)
        context.scene.curr_idx = len(self.points_bar) - 1
        return True
    
    def invalidate_target(self):
        global is_running
        is_running = False
        
        del self.target[utils.key_name]
        utils.reset_spline_server(spline.comm)
        bpy.data.objects.remove(self.tan, do_unlink=True)
        self.report({'WARNING'}, "Geometry modified, curves on the objects invalidated")        
    
def menu_func(self, context):
    self.layout.operator(EditCurveOperator.bl_idname, text="Edit bezier spline")

# Register and add to the "view" menu (required to also use F3 search "Raycast View Modal Operator" for quick access)
def register():
    bpy.utils.register_class(EditCurveOperator)
    bpy.types.VIEW3D_MT_view.append(menu_func)


def unregister():
    bpy.utils.unregister_class(EditCurveOperator)
    bpy.types.VIEW3D_MT_view.remove(menu_func)


if __name__ == "__main__":
    register()