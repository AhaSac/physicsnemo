from pathlib import Path
from mesh_backend import launch, generated_boundary_ids, face_quality
from run_meshing import load_config

out = Path(__file__).parent.resolve() / 'outputs/probe'
s = launch(out, load_config('poly'))
try:
    s.transcript.start(file_name=str(out / 'diagnose.trn'), write_to_stdout=True)
    s.workflow.InitializeWorkflow(WorkflowType='Watertight Geometry')
    s.tui.file.read_mesh(str(out / 'surface_improved.msh.h5'))
    u = s.meshing_utilities
    try:
        print('HELPER', generated_boundary_ids(s), flush=True)
    except Exception as error:
        print('HELPER_ERROR', str(error), flush=True)
    for label, query in [
        ('all_ids', lambda: u.get_face_zones(filter='*')),
        ('all_names', lambda: u._face_zones_str_fdl()),
        ('objects', lambda: u.get_objects(type_name='mesh')),
        ('object_faces', lambda: u.get_face_zones_of_object(object_name='__1-4-__1-4')),
        ('names_all', lambda: u.convert_zone_ids_to_name_strings(zone_id_list=u.get_face_zones(filter='*'))),
        ('names_subset', lambda: u.convert_zone_ids_to_name_strings(zone_id_list=[28,29,30,31,32])),
        ('name_query', lambda: u.get_face_quality_limits(face_zone_name_pattern='zone3impeller_wall', measure='Skewness')),
        ('workflow', lambda: s.workflow.TaskObject.get_state()),
    ]:
        try:
            print(label, repr(query()), flush=True)
        except Exception as error:
            print(label, 'ERROR', str(error), flush=True)
finally:
    s.exit()
