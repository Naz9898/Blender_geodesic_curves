import bpy
import bmesh
import sys
import socket
import subprocess
from bpy_extras import view3d_utils
from mathutils import Vector

bpy.types.Scene.decastel_jau   = bpy.props.BoolProperty(default=True) 
bpy.types.Scene.subdivisions = bpy.props.IntProperty(min=0, max=10, default=4)

#----------KEY FUNCTION----------------------------------------------------
key_name = "geo_key"

def get_int(self):
    return self["value"]

def set_int(self, value):
    self["value"] = value

if not hasattr(bpy.types.Scene, "total"):
    bpy.types.Scene.total = bpy.props.IntProperty(get=get_int, set=set_int)
    bpy.types.Scene.total = 0

def getObjByKey(key):
    for obj in  bpy.context.scene.objects:
        if key_name in obj and obj[key_name] == key: return obj
    return None
    

#----------BPY WRAPPERS -------------------------------------------------

#Wrapper for barycentric coordinates
class BarycentriCoord(bpy.types.PropertyGroup):
    f: bpy.props.IntProperty()
    u: bpy.props.FloatProperty()
    v: bpy.props.FloatProperty()
    
    def get(self):
        return [self.f, [self.u, self.v]]
bpy.utils.register_class(BarycentriCoord)


#Wrapper for CurveInfo 
class CurveInfo(bpy.types.PropertyGroup):
    points_bar: bpy.props.CollectionProperty(type=BarycentriCoord)
    is_closed:  bpy.props.BoolProperty()
    smooth:  bpy.props.BoolProperty(default=True)
bpy.utils.register_class(CurveInfo)

class ObjCurvesItem(bpy.types.PropertyGroup):
    key: bpy.props.StringProperty()
    value: bpy.props.CollectionProperty(type=CurveInfo)
bpy.utils.register_class(ObjCurvesItem)

bpy.types.Scene.obj_curves = bpy.props.CollectionProperty(type=ObjCurvesItem)

#To mimic dictionary
def push_key(key):
    my_item = bpy.context.scene.obj_curves.add()
    my_item.key = key

#TODO: join add_curve and update_curve (sharing code)
def add_curve(key, points_bar):
    obj_item = obj_curves_get(key) 
    curve_item = obj_item.value.add()
    
    for p in points_bar:
        p_bar_item = curve_item.points_bar.add()
        p_bar_item.f = p[0]
        p_bar_item.u = p[1][0]
        p_bar_item.v = p[1][1]

def update_curve(key, info):
    idx = key.find('o')
    curve_idx = int(key[1:idx])
    obj_key = key[idx:]
    
    obj_item = obj_curves_get(obj_key)
    curve_item = obj_item.value[curve_idx]
    curve_item.points_bar.clear()
    curve_item.points_idx.clear()
    #Copy barycentric coords
    points_bar = info.points_bar
    for p in points_bar:
        p_bar_item = curve_item.points_bar.add()
        p_bar_item.f = p[0]
        p_bar_item.u = p[1][0]
        p_bar_item.v = p[1][1]
    #Copy indices
    points_idx = info.points_idx
    for idx in points_idx:
        idx_item = curve_item.points_idx.add()
        idx_item.val = idx
        
def add_point(points_bar, point):
    p_bar_item = points_bar.add()
    #TODO: subsitute with update point
    p_bar_item.f = point[0]
    p_bar_item.u = point[1][0]
    p_bar_item.v = point[1][1]
    
def update_point(p_bar_item, point):
    p_bar_item.f = point[0]
    p_bar_item.u = point[1][0]
    p_bar_item.v = point[1][1]

def obj_curves_get(key):
    for item in bpy.context.scene.obj_curves:
        if item.key == key: return item
    return None

def print_obj_curves():
    print("Number of context geo objs: ",  len(bpy.context.scene.obj_curves))
    for item in bpy.context.scene.obj_curves:
        print("key: ", item.key, " n_curves: ", len(item.value))
    
#----------C++ ENGINE COMMUNICATION FUNCTION-----------------------------

class ServerCommunication:
    def __init__(self):
        self.s = None #Socket
        self.process = None #Subprocess for c++ engine
        self.obj_key = None #Name of the current working object

#Create TCP socket for geodesic spline calculations                
def create_socket():
    HOST = "127.0.0.1"  # The server's hostname or IP address
    PORT = 27015  # The port used by the server

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    return sock

#Run C++ engine in subprocess    
def run_spline_server(directory, comm):
    command = directory + "\\bezier\\bin\\splinegui.exe"
    mesh = directory + "\\bezier\\data\\tmp.obj"
    comm.process = subprocess.Popen([command, mesh], 
        universal_newlines=True,
        stdout=subprocess.PIPE
        )
 
    line = comm.process.stdout.readline()
    line = comm.process.stdout.readline()
    print("Waited for line ", line)
    comm.s = create_socket()
    print("New socket: ", comm.s)

#Kill C++ engine subprocess   
def close_spline_server(comm):
    comm.s.sendall(b"a\n")
    reset_spline_server(comm)
    
def reset_spline_server(comm):
    subprocess.Popen("TASKKILL /F /PID {pid} /T".format(pid=comm.process.pid))
    comm.process = None
    comm.s.shutdown(socket.SHUT_RDWR)
    comm.s.close()
    comm.obj_key = None
    print("Closed socket: ", comm.s)

#Save mesh in tmp.obj that will be the input for the C++ engine
#Needed to keep data structure alligned with the C++ engine
def save_file(mesh, name): 
    with open(name, 'w+') as f1:
        for p in mesh.vertices:
            coord = p.co
            f1.write("v " +  str(coord[0]) + " " + str(coord[1]) + " " + str(coord[2]) + "\n" )
        for f in mesh.polygons:
            v1, v2, v3 = f.vertices 
            f1.write("f " + str(v1+1) + " " + str(v2+1) + " " + str(v3+1) + "\n")      
            
#Send control points in barycentric coords to server
def send_point_bar(sock, points_bar):
    send = ""
    for point in points_bar:
        send += pbar2str(point)
    sock.sendall(send.encode())
    
#Send final two points of current polygon and new one
def send_tan_extension(sock, p1, p2):
    send = "n\n"
    send += pbar2str( p1.get() ) #For tangent calculation
    send += pbar2str( p2.get() ) #Start point of the new curve
    sock.sendall(send.encode())

def send_point_eval(sock, points_bar, t0):
    send = "p\n" + str(t0) + "\n"
    for point in points_bar:
        send += pbar2str(point)
    sock.sendall(send.encode())

def send_split(sock, points_bar, t0):
    send = "s\n" + str(t0) + "\n"
    for point in points_bar:
        send += pbar2str(point)
    sock.sendall(send.encode())
    
def pbar2str(point):
    face, coord = point
    return str(face) + "\n" + str(coord[0]) + "\n" + str(coord[1]) + "\n" 

#Read single polyline from the server
#Input: obj if want the points in 3d coords (barycentric otherwise), remaining data if present (for successive read calls)
#Output: polyline in barycentric coordinates and remaining data if present (for successive read calls)
#Note: remainder variable needed only if need to read multiple consecutive polylines
def recv_points(sock, remainders = (None, [])):
    poly = []
    n = -1
    #Line_remainder: if row has been separated in two different messages
    #Data_remainder: after finished reading there may be remaining data for following poly read
    #Note: only one of the two possible
    line_remainder, data_remainder = remainders
    while n < 0 or len(poly) < n:   
        #Read data if there is none 
        if len(data_remainder) == 0: 
            data = sock.recv(2048).decode()
            #If last line was splitted append it in the front
            if line_remainder is not None: 
                data = line_remainder + data
                line_remainder = None
            poly_points = data.splitlines(True)    
        #Get there remaining data if present
        else: 
            poly_points = data_remainder
            data_remainder = []  
        #Read points
        for idx in range(len(poly_points)):
            p = poly_points[idx]
            #Truncated line
            if p.count('\n') != 1 and p[-1] != '\n': 
                line_remainder = p
                break
            #First line is polyline len
            if n < 0: n = int(p)
            #Following lines are points
            else:        
                coords = p.split()
                poly.append( (int(coords[0]), float(coords[1]), float(coords[2])) )
                #Check if finished reading
                if len(poly) == n: 
                    if idx < len(poly_points)-1: data_remainder = poly_points[idx+1:]
                    break
    return poly, (line_remainder, data_remainder)

def get_straight_path(sock, obj, p1, p2):
    send = "l\n"
    send += pbar2str( p1 )
    send += pbar2str( p2 )
    sock.sendall(send.encode())
    path, _ = recv_points(sock)
    return path

def get_curve(sock, obj, points_bar):
    send_point_bar(sock, points_bar)
    curve, _ = recv_points(sock)
    convert_coords(obj, curve)
    return curve

#Receive polygon and curve
#OUTPUT: control polygon points idx in the mesh, control points idx in the previous list, curve points idx
"""
def get_all_data(sock, obj, points_bar):
    #Send control points to the engine
    send_point_bar(sock, points_bar)
    control_points = []
    control_points_idx = [0]
    #Receive control polygon
    remainder = (None, [])
    for i in range(len(points_bar) - 1):
        tmp, remainder = recv_points(sock, remainder)
        control_points_idx.append( control_points_idx[-1] + len(tmp) - 1 )
        if len( control_points ) != 0:
            tmp = tmp[1:]
        control_points = control_points + tmp
    convert_coords(obj, control_points)
    #Receive curve
    curve, _ = recv_points(sock, remainder)
    convert_coords(obj, curve)
    return control_points, control_points_idx, curve


def get_extension(sock, obj):
    control_points = []
    control_points_idx = [0]
    #Receive control polygon
    remainder = (None, [])
    for i in range(3):
        tmp, remainder = recv_points(sock, remainder)
        control_points_idx.append( control_points_idx[-1] + len(tmp) - 1 )
        if len( control_points ) != 0:
            tmp = tmp[1:]
        control_points = control_points + tmp
    convert_coords(obj, control_points)
    #Receive curve
    curve, _ = recv_points(sock, remainder)
    convert_coords(obj, curve)
    return control_points, control_points_idx, curve

#Convert list of points in barycentric coordinates in 3d points
def obj_to_world(ob, p):
    mat = ob.matrix_world
    mesh = ob.data
    return mat@p
"""
#Convert list of points in barycentric coordinates in 3d points
def convert_coords(ob, points):
    mat = ob.matrix_world
    mesh = ob.data
    
    for i in range(len(points)):
        face_idx, a, b = points[i]
        face = mesh.polygons[face_idx]
        v1, v2, v3 = face.vertices
        points[i] = mat@(mesh.vertices[v1].co*(1-a-b) + mesh.vertices[v2].co*a + mesh.vertices[v3].co*b)

#----------EDITING UTILS--------------------------------------------------------
def triangulate_object(obj):
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)

    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
    
    bm.to_mesh(me)
    bm.free()
    
def ray_cast(context, event, coord = None):
    """Run this function on left mouse, execute the ray cast"""
    # get the context arguments
    scene = context.scene
    region = context.region
    rv3d = context.region_data
    if coord is None: coord = event.mouse_region_x, event.mouse_region_y

    # get the ray from the viewport and mouse
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

    ray_target = ray_origin + view_vector

    def visible_objects_and_duplis():
        """Loop over (object, matrix) pairs (mesh only)"""

        depsgraph = context.evaluated_depsgraph_get()
        for dup in depsgraph.object_instances:
            if dup.is_instance:  # Real dupli instance
                obj = dup.instance_object
                yield (obj, dup.matrix_world.copy())
            else:  # Usual object
                obj = dup.object
                yield (obj, obj.matrix_world.copy())

    def obj_ray_cast(obj, matrix):
        """Wrapper for ray casting that moves the ray into object space"""

        # get the ray relative to the object
        matrix_inv = matrix.inverted()
        ray_origin_obj = matrix_inv @ ray_origin
        ray_target_obj = matrix_inv @ ray_target
        ray_direction_obj = ray_target_obj - ray_origin_obj

        # cast the ray
        success, location, normal, face_index = obj.ray_cast(ray_origin_obj, ray_direction_obj)

        if success:
            return location, normal, face_index
        else:
            return None, None, None

    # cast rays and find the closest object
    best_length_squared = -1.0
    best_obj = None
    best_hit = None
    best_norm = None
    best_face = None

    #print("Ray cast start")
    for obj, matrix in visible_objects_and_duplis():

        if obj.type == 'MESH' and len(obj.data.polygons) > 0:
            hit, normal, face_index = obj_ray_cast(obj, matrix)
            if hit is not None:
                hit_world = matrix @ hit
                scene.cursor.location = hit_world
                length_squared = (hit_world - ray_origin).length_squared
                if best_obj is None or length_squared < best_length_squared:
                    best_length_squared = length_squared
                    best_obj = obj
                    
                    best_hit = hit
                    best_norm = normal
                    best_face = face_index
                    
    # now we have the object under the mouse cursor,
    # we could do lots of stuff but for the example just select.
    if best_obj is not None:
        # for selection etc. we need the original object,
        # evaluated objects are not in viewlayer
        best_original = best_obj.original
        best_original.select_set(True)
        context.view_layer.objects.active = best_original
        return best_obj, best_hit, best_norm, best_face
    return None, None, None, None

