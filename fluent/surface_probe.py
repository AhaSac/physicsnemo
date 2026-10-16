import json
from pathlib import Path
import ansys.fluent.core as p

out = Path(__file__).resolve().parent / 'outputs/probe'
s = p.launch_fluent(fluent_path=r'C:\Program Files\ANSYS Inc\v242\fluent\ntbin\win64\fluent.exe', product_version='24.2.0',
                    mode='meshing', precision='double', processor_count=4,
                    ui_mode='no_gui', cwd=str(out), start_timeout=120, start_watchdog=False)
try:
    s.tui.file.read_mesh(str(out / 'surface.msh.h5'))
    u = s.meshing_utilities
    objects = u.get_objects(type_name='mesh')
    print('OBJECTS', objects, flush=True)
    faces = u.get_face_zones_of_object(object_name=objects[0])
    print('MESH_FACES', faces, flush=True)
    print('BEFORE_FACES', u.get_face_quality_limits(face_zone_id_list=faces, measure='Skewness'), flush=True)
    print('IMPROVE_DEFAULT', s.meshing.ImproveSurfaceMesh.create_instance().get_state(), flush=True)
    print('RESULT', s.meshing.ImproveSurfaceMesh(MeshObject=objects[0], FaceQualityLimit=0.65, SQMinSize=0.05), flush=True)
    print('AFTER_FACES', u.get_face_quality_limits(face_zone_id_list=faces, measure='Skewness'), flush=True)
    s.tui.file.write_mesh(str(out / 'surface_improved.msh.h5'))
finally:
    s.exit()
