import bpy
import bmesh
import socket
import subprocess
from bpy_extras import view3d_utils
from mathutils import Vector

#----------C++ ENGINE COMMUNICATION FUNCTION-----------------------------

#Create TCP socket for geodesic spline calculations                
def create_socket():
    HOST = "127.0.0.1"  # The server's hostname or IP address
    PORT = 27015  # The port used by the server

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    return sock

#Run C++ engine in subprocess    
def run_spline_server(directory):
    command = directory + "\\bezier\\bin\\splinegui.exe"
    mesh = directory + "\\bezier\\data\\tmp.obj"
    process = subprocess.Popen([command, mesh], 
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
        shell=True, universal_newlines=True)
    return process

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
        face = point[0]
        coord = point[1]
        send += str(face) + "\n"
        for n in coord:
            send += str(n) + "\n"
    sock.sendall(send.encode())

#Read single polyline from the server
#Output: polyline in barycentric coordinates and remaining data if present
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
            #If last line was splitted append append it in the front
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

#Receive polygon and curve
#OUTPUT: control polygon points idx in the mesh, control points idx in the previous list, curve points idx
def get_all_data(sock, obj_name, points_bar):
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
    convert_coords(obj_name, control_points)
    #Receive curve
    curve, _ = recv_points(sock, remainder)
    convert_coords(obj_name, curve)
    return control_points, control_points_idx, curve

#Convert list of points in barycentric coordinates in 3d points
def convert_coords(obj_name, points):
    mesh = bpy.data.objects[obj_name].data
    for i in range(len(points)):
        face_idx, a, b = points[i]
        face = mesh.polygons[face_idx]
        v1, v2, v3 = face.vertices
        points[i] = mesh.vertices[v1].co*(1-a-b) + mesh.vertices[v2].co*a + mesh.vertices[v3].co*b 

#----------EDITING UTILS--------------------------------------------------------
def triangulate_object(obj):
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)

    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
    
    bm.to_mesh(me)
    bm.free()
    
def ray_cast(context, event):
    """Run this function on left mouse, execute the ray cast"""
    # get the context arguments
    scene = context.scene
    region = context.region
    rv3d = context.region_data
    coord = event.mouse_region_x, event.mouse_region_y

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

    for obj, matrix in visible_objects_and_duplis():
        if obj.type == 'MESH':
            hit, normal, face_index = obj_ray_cast(obj, matrix)
            if hit is not None:
                hit_world = matrix @ hit
                scene.cursor.location = hit_world
                length_squared = (hit_world - ray_origin).length_squared
                if best_obj is None or length_squared < best_length_squared:
                    best_length_squared = length_squared
                    best_obj = obj

    # now we have the object under the mouse cursor,
    # we could do lots of stuff but for the example just select.
    if best_obj is not None:
        # for selection etc. we need the original object,
        # evaluated objects are not in viewlayer
        best_original = best_obj.original
        best_original.select_set(True)
        context.view_layer.objects.active = best_original
        #print(hit)
        return best_obj, hit, normal, face_index
    else: return None, None, None, None

