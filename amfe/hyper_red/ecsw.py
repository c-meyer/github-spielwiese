"""
TODO: Write introduction to ECSW
"""

import time
import copy
import numpy as np
import scipy as sp

from ..mechanical_system import ReducedSystem

__all__ = ['ECSWSystem',
           'reduce_mechanical_system_ecsw',
           'sparse_nnls',
          ]


def sparse_nnls(G, b, tau, conv_stats=False, verbose=True):
    r'''
    Run the sparse NNLS-solver in order to find a sparse vector xi satisfying

    .. math::
        || G \xi - b ||_2 \leq \tau ||b||_2 \quad\text{with}\quad \min||\xi||_0

    Parameters
    ----------
    G : ndarray, shape: (n*m, no_of_elements)
        force contribution matrix
    b : ndarray, shape: (n*m)
        force contribution vector
    tau : float
        tolerance
    conv_info : bool
        Flag for setting, that more detailed output is produced with
        convergence information.

    Returns
    -------
    indices : ndarray, shape: (k,)
        The indices of the non-zero elements.
    xi_red : ndarray, shape: (k,)
        The values of the non-zero elements.
    stats : ndarray
        Infos about the convergence of the system. The first column shows the
        size of the active set, the second column the residual. If conv_info is
        set to False, an empty array is returned.

    References
    ----------
    .. [1]  C. L. Lawson and R. J. Hanson. Solving least squares problems,
            volume 15. SIAM, 1995.

    .. [2]  T. Chapman, P. Avery, P. Collins, and C. Farhat. Accelerated mesh
            sampling for the hyper reduction of nonlinear computational models.
            International Journal for Numerical Methods in Engineering, 2016.

    '''
    no_of_elements = G.shape[1]
    norm_b = np.linalg.norm(b)
    r = b

    xi = np.zeros(no_of_elements) # the resulting vector
    zeta = np.zeros(no_of_elements) # the trial vector which is iterated over

    # Boolean active set; allows quick and easys indexing through masking with
    # high performance at the same time
    active_set = np.zeros(no_of_elements, dtype=bool)

    stats = []
    while np.linalg.norm(r) > tau * norm_b:
        mu = G.T @ r
        idx = np.argmax(mu)
        active_set[idx] = True
        print('Added element {}'.format(idx))
        while True:
            # Trial vector zeta is solved for the sparse solution
            zeta[~active_set] = 0
            G_red = G[:,active_set]
            zeta[active_set] = sp.linalg.solve(G_red.T @ G_red, G_red.T @ b)

            # check, if gathered solution is full positive
            if np.min(zeta[active_set]) >= 0:
                xi[:] = zeta[:]
                break
            else: # remove the negative elements from the active set
                # Get all elements which violate the constraint, i.e. are in the
                # active set and are smaller than zero
                mask = np.logical_and(zeta <= 0, active_set)

                ele_const = np.argmin(xi[mask] / (xi[mask] - zeta[mask]))
                const_idx = np.where(mask)[0][ele_const]
                print('Remove element {} '.format(const_idx) +
                       'violating the constraint.')
                # Amplify xi with the difference of zeta and xi such, that the
                # largest mismatching negative point becomes zero.
                alpha = np.min(xi[mask] / (xi[mask] - zeta[mask]))
                xi += alpha * (zeta - xi)
                # Set active set manually as otherwise floating point roundoff
                # errors are not considered.
                # active_set = xi != 0
                active_set[const_idx] = False

        r = b - G[:,active_set] @ xi[active_set]
        if verbose:
            print('snnls: residual', np.linalg.norm(r),
                  'No of active elements:', len(np.where(xi)[0]))
        if conv_stats:
            stats.append((len(np.where(xi)[0]), np.linalg.norm(r)))

    # sp.optimize.nnls(A, b)
    indices = np.where(xi)[0] # remove the nasty tupel from np.where()
    xi_red = xi[active_set]
    stats = np.array(stats)
    return indices, xi_red, stats


class ECSWSystem(ReducedSystem):
    '''
    Hyper Reduced system using ECSW for the redcution.
    '''

    def __init__(self, **kwargs):
        '''

        '''
        super().__init__(self, **kwargs)
        # values to be computed in reduce_mesh
        self.weights = None
        self.weight_idx = None

    def reduce_mesh(self, W_red, tau=0.001, verbose=True):
        '''
        Compute a reduced mesh using a sparse NNLS solver for gaining the
        weights.

        Parameters
        ----------
        W_red : ndarray, shape(n_red, no_of_snapshots)
            Snapshot training matrix for which the energy equality is ensured.
        tau : float, optional
            tolerance for fitting the best solution

        Returns
        -------
        weight_indices : ndarray
            indices of members in the reduced mesh
        weights : ndarray
            weights for reduced mesh
        stats : ndarray
            statistics about the convergence of the sparse NNLS solver. The
            first column shows the size of the active set, the secont column
            the residual. If `verbose=False`, an empty array is returned.

        Note
        ----
        The indices and weights of the reduced mesh are also internally saved.
        '''
        print('Start reducing mesh with tolerance tau={0:3.4}'.format(tau))
        t1 = time.time()
        W_unconstr = self.V_unconstr @ W_red
        print('Assemble matrices G and b...')
        G, b = self.assembly_class.assemble_g_and_b(self.V_unconstr,
                                                    W_unconstr,
                                                    verbose=verbose)
        print('') # newline as dots are written without newline
        print('Solve sparse NNLS problem')
        xi_indices, xi, stats = sparse_nnls(G, b, tau, verbose=verbose,
                                            conv_stats=verbose)
        self.weight_idx = xi_indices
        self.weights = xi
        t2 = time.time()

        print('Mesh successfully reduced to', len(xi), 'Elements.')
        print('Full mesh size is', self.mesh_class.no_of_elements, 'Elements.')
        print('Time taken for mesh reduction: {0:3.4} seconds.'.format(t2-t1))
        return xi_indices, xi, stats

    def K_and_f(self, u=None, t=0):
        if u is None:
            u = np.zeros(self.V.shape[1])

        if self.assembly_type == 'direct':
            K, f_int = self.assembly_class.assemble_k_and_f_hyper(
                          self.V_unconstr,self.weight_idx, self.weights, u, t)
        elif self.assembly_type == 'indirect':
            K, f_int = self.assembly_class.assemble_k_and_f_hyper_no_inplace(
                          self.V_unconstr,self.weight_idx, self.weights, u, t)
        else:
            raise ValueError('The given assembly type for a reduced system '
                             + 'is not valid.')
        return K, f_int

    def K(self, u=None, t=0):
        if u is None:
            u = np.zeros(self.V.shape[1])

        if self.assembly_type == 'direct':
            K, f_int = self.assembly_class.assemble_k_and_f_hyper(
                          self.V_unconstr,self.weight_idx, self.weights, u, t)
        elif self.assembly_type == 'indirect':
            K, f_int = self.assembly_class.assemble_k_and_f_hyper_no_inplace(
                          self.V_unconstr,self.weight_idx, self.weights, u, t)
        else:
            raise ValueError('The given assembly type for a reduced system '
                             + 'is not valid.')
        return K

    def f_int(self, u, t=0):
        if u is None:
            u = np.zeros(self.V.shape[1])

        if self.assembly_type == 'direct':
            K, f_int = self.assembly_class.assemble_k_and_f_hyper(
                          self.V_unconstr,self.weight_idx, self.weights, u, t)
        elif self.assembly_type == 'indirect':
            K, f_int = self.assembly_class.assemble_k_and_f_hyper_no_inplace(
                          self.V_unconstr,self.weight_idx, self.weights, u, t)
        else:
            raise ValueError('The given assembly type for a reduced system '
                             + 'is not valid.')
        return f_int

    def export_paraview(self, filename, field_list=None):

        # take care of None field lists
        if field_list is None:
            new_field_list = []
        else:
            new_field_list = field_list.copy()

        # the h5 dictionary
        h5_xi_dict = {'ParaView':True,
             'AttributeType':'Scalar',
             'Center':'Cell',
             'Name':'weights_hyper_red',
             'NoOfComponents':1,
             }

        xi = np.zeros(self.mesh_class.no_of_elements)
        xi[self.weight_idx] = self.weights

        new_field_list.append((xi, h5_xi_dict))

        ReducedSystem.export_paraview(self, filename, new_field_list)
        return

def reduce_mechanical_system_ecsw(mechanical_system, V, overwrite=False,
                                   assembly='indirect'):
    '''
    Reduce the given mechanical system with the linear basis V and the given
    weights.

    Parameters
    ----------
    mechanical_system : instance of MechanicalSystem
        Mechanical system which will be transformed to a ReducedSystem.
    V : ndarray, shape (N_constrained, n_red)
        Reduction Basis for the reduced system
    overwrite : bool, optional
        switch, if mechanical system should be overwritten (is less memory
        intensive for large systems) or not.
    assembly : str {'direct', 'indirect'}
        flag setting, if direct or indirect assembly is done. For larger
        reduction bases, the indirect method is much faster.

    Returns
    -------
    reduced_system : instance of ReducedSystem
        Reduced system with same properties of the mechanical system and
        reduction basis V

    Example
    -------

    '''

    if overwrite:
        reduced_sys = mechanical_system
    else:
        reduced_sys = copy.deepcopy(mechanical_system)
    reduced_sys.__class__ = ECSWSystem
    reduced_sys.V = V.copy()
    reduced_sys.V_unconstr = reduced_sys.dirichlet_class.unconstrain_vec(V)
    reduced_sys.weights = None
    reduced_sys.weight_idx = None
    reduced_sys.u_red_output = []
    reduced_sys.M_constr = None
    # reduce Rayleigh damping matrix
    if reduced_sys.D_constr is not None:
        reduced_sys.D_constr = V.T @ reduced_sys.D_constr @ V
    reduced_sys.assembly_type = assembly
    print('The system is hyper reduced now. It still needs to build the ' +
          'reduced mesh.')
    return reduced_sys
