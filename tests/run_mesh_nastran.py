"""
Load a NASTRAN mesh 
"""

import numpy as np
import pandas as pd
import amfe


#%%

filename = amfe.amfe_dir('meshes/nastran/conrod.bdf')
my_material = amfe.KirchhoffMaterial()
my_mesh = amfe.Mesh()
my_mesh.import_bdf(filename)

my_mesh.load_group_to_mesh(1, my_material)
my_mesh.load_group_to_mesh(10, my_material)
my_mesh.load_group_to_mesh(20, my_material)

#%% Deflate the mesh
my_mesh.deflate_mesh()

#%%

my_assembly = amfe.Assembly(my_mesh)
my_assembly.preallocate_csr()

u0 = np.zeros(my_mesh.no_of_dofs)
K_unconstr, f_unconstr = my_assembly.assemble_k_and_f(u=u0, t=1)

my_mesh.save_mesh_xdmf('results/nastran_meshes/mesh_nastran')

#%%

K_reord, perm = amfe.tools.reorder_sparse_matrix(K_unconstr)
