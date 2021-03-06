# Copyright (c) 2017, Lehrstuhl fuer Angewandte Mechanik, Technische
# Universitaet Muenchen.
#
# Distributed under BSD-3-Clause License. See LICENSE-File for more information
#
"""
Element Module in which the Finite Elements are described on Element level.

This Module is arbitrarily extensible. The idea is to use the basis class
Element which provides the functionality for an efficient solution of a time
integration by only once calling the internal tensor computation and then
extracting the tangential stiffness matrix and the internal force vector in one
run.

Some remarks resulting in the observations of the profiler:
Most of the time is spent with python-functions, when they are used. For
instance the kron-function in order to build the scattered geometric stiffness
matrix or the trace function are very inefficient. They can be done better when
using direct functions.

If some element things are really time critical, it is recommended to port the
heavy computation to FORTRAN. This can be achieved by using the provided f2py
routines and reprogram the stuff for the own use.

"""

__all__ = ['Element',
           'Tri3',
           'Tri6',
           'Quad4',
           'Quad8',
           'Tet4',
           'Tet10',
           'Hexa8',
           'Hexa20',
           'Bar2Dlumped',
           'BoundaryElement',
           'Tri3Boundary',
           'Tri6Boundary',
           'Quad4Boundary',
           'Quad8Boundary',
           'LineLinearBoundary',
           'LineQuadraticBoundary',
           ]

import numpy as np
from numpy import sqrt

# Try to import Fortran routines
use_fortran = False

try:
    import amfe.f90_element
    use_fortran = True
except Exception:
    print('''Python was not able to load the fast fortran element routines.''')

#use_fortran = False
#print('Explicit no use of fortran routines in the Element routine')

def scatter_matrix(Mat, ndim):
    '''
    Scatter the symmetric (geometric stiffness) matrix to all dofs.

    What is basically done is to perform the np.kron(Mat, eye(ndim))

    Parameters
    ----------
    Mat : ndarray
        Matrix that should be scattered
    ndim : int
        number of dimensions of finite element. If it's a 2D element, ndim=2,
        if 3D, ndim=3

    Returns
    -------
    Mat_scattered : ndarray
        scattered matrix

    '''
    dof_small_row = Mat.shape[0]
    dof_small_col = Mat.shape[1]
    Mat_scattered = np.zeros((dof_small_row*ndim, dof_small_col*ndim))

    for i in range(dof_small_row):
        for j in range(dof_small_col):
            for k in range(ndim):
                Mat_scattered[ndim*i+k,ndim*j+k] = Mat[i,j]
    return Mat_scattered


def compute_B_matrix(B_tilde, F):
    '''
    Compute the B-matrix used in Total Lagrangian Finite Elements.

    Parameters
    ----------
    F : ndarray
        deformation gradient (dx_dX)
    B_tilde : ndarray
        Matrix of the spatial derivative of the shape functions: dN_dX

    Returns
    -------
    B : ndarray
        B matrix such that {delta_E} = B @ {delta_u^e}

    Notes
    -----
    When the Voigt notation is used in this Reference, the variables are
    denoted with curly brackets.
    '''

    no_of_nodes = B_tilde.shape[0]
    no_of_dims = B_tilde.shape[1] # spatial dofs per node, i.e. 2 for 2D or 3 for 3D
    b = B_tilde
    B = np.zeros((no_of_dims*(no_of_dims+1)//2, no_of_nodes*no_of_dims))
    F11 = F[0,0]
    F12 = F[0,1]
    F21 = F[1,0]
    F22 = F[1,1]

    if no_of_dims == 3:
        F13 = F[0,2]
        F31 = F[2,0]
        F23 = F[1,2]
        F32 = F[2,1]
        F33 = F[2,2]

    for i in range(no_of_nodes):
        if no_of_dims == 2:
            B[:, i*no_of_dims : (i+1)*no_of_dims] = [
                [F11*b[i,0], F21*b[i,0]],
                [F12*b[i,1], F22*b[i,1]],
                [F11*b[i,1] + F12*b[i,0], F21*b[i,1] + F22*b[i,0]]]
        else:
            B[:, i*no_of_dims : (i+1)*no_of_dims] = [
                [F11*b[i,0], F21*b[i,0], F31*b[i,0]],
                [F12*b[i,1], F22*b[i,1], F32*b[i,1]],
                [F13*b[i,2], F23*b[i,2], F33*b[i,2]],
                [F12*b[i,2] + F13*b[i,1],
                     F22*b[i,2] + F23*b[i,1], F32*b[i,2] + F33*b[i,1]],
                [F13*b[i,0] + F11*b[i,2],
                     F23*b[i,0] + F21*b[i,2], F33*b[i,0] + F31*b[i,2]],
                [F11*b[i,1] + F12*b[i,0],
                     F21*b[i,1] + F22*b[i,0], F31*b[i,1] + F32*b[i,0]]]
    return B

# Overloading the python functions with Fortran functions, if possible
if use_fortran:
    compute_B_matrix = amfe.f90_element.compute_b_matrix
    scatter_matrix = amfe.f90_element.scatter_matrix


class Element():
    '''
    Anonymous baseclass for all elements. It contains the methods needed
    for the computation of the element stuff.

    Attributes
    ----------
    material : instance of amfe.HyperelasticMaterial
        Class containing the material behavior.
    name : str
        Name for the postprocessing tool to identify the characteristics of the
        element

    '''
    name = None

    def __init__(self, material=None):
        '''
        Parameters
        ----------
        material : amfe.HyperelasticMaterial - object
            Object handling the material
        '''
        self.material = material
        self.K = None
        self.f = None
        self.S = None
        self.E = None

    def _compute_tensors(self, X, u, t):
        '''
        Virtual function for the element specific implementation of a tensor
        computation routine which will be called before _k_int and _f_int
        will be called. For many computations the tensors need to be computed
        the same way.
        '''
        pass

    def _m_int(self, X, u, t=0):
        '''
        Virtual function for the element specific implementation of the mass
        matrix;
        '''
        pass

    def k_and_f_int(self, X, u, t=0):
        '''
        Returns the tangential stiffness matrix and the internal nodal force
        of the Element.

        Parameters
        ----------
        X : ndarray
            nodal coordinates given in Voigt notation (i.e. a 1-D-Array
            of type [x_1, y_1, z_1, x_2, y_2, z_2 etc.])
        u : ndarray
            nodal displacements given in Voigt notation
        t : float
            time

        Returns
        -------
        k_int : ndarray
            The tangential stiffness matrix (ndarray of dimension (ndim, ndim))
        f_int : ndarray
            The nodal force vector (ndarray of dimension (ndim,))

        Examples
        --------
        TODO

        '''
        self._compute_tensors(X, u, t)
        return self.K, self.f

    def k_int(self, X, u, t=0):
        '''
        Returns the tangential stiffness matrix of the Element.

        Parameters
        ----------
        X : ndarray
            nodal coordinates given in Voigt notation (i.e. a 1-D-Array of
            type [x_1, y_1, z_1, x_2, y_2, z_2 etc.])
        u : ndarray
            nodal displacements given in Voigt notation
        t : float
            time

        Returns
        -------
        k_int : ndarray
            The tangential stiffness matrix (numpy.ndarray of type ndim x ndim)

        '''
        self._compute_tensors(X, u, t)
        return self.K

    def f_int(self, X, u, t=0):
        '''
        Returns the internal element restoring force f_int

        Parameters
        ----------
        X : ndarray
            nodal coordinates given in Voigt notation (i.e. a 1-D-Array of
            type [x_1, y_1, z_1, x_2, y_2, z_2 etc.])
        u : ndarray
            nodal displacements given in Voigt notation
        t : float, optional
            time, default value: 0.

        Returns
        -------
        f_int : ndarray
            The nodal force vector (numpy.ndarray of dimension (ndim,))

        '''
        self._compute_tensors(X, u, t)
        return self.f

    def m_and_vec_int(self, X, u, t=0):
        '''
        Returns mass matrix of the Element and zero vector of size X.


        Parameters
        ----------
        X : ndarray
            nodal coordinates given in Voigt notation (i.e. a 1-D-Array of
            type [x_1, y_1, z_1, x_2, y_2, z_2 etc.])
        u : ndarray
            nodal displacements given in Voigt notation
        t : float, optional
            time, default value: 0.

        Returns
        -------
        m_int : ndarray
            The consistent mass matrix of the element (numpy.ndarray of
            dimension (ndim,ndim))
        vec : ndarray
            vector (containing zeros) of dimension (ndim,)

        '''
        return self._m_int(X, u, t), np.zeros_like(X)

    def m_int(self, X, u, t=0):
        '''
        Returns the mass matrix of the element.

        Parameters
        ----------
        X : ndarray
            nodal coordinates given in Voigt notation (i.e. a 1-D-Array of
            type [x_1, y_1, z_1, x_2, y_2, z_2 etc.])
        u : ndarray
            nodal displacements given in Voigt notation
        t : float, optional
            time, default value: 0.

        Returns
        -------
        m_int : ndarray
            The consistent mass matrix of the element (numpy.ndarray of
            dimension (ndim,ndim))

        '''
        return self._m_int(X, u, t)

    def k_f_S_E_int(self, X, u, t=0):
        '''
        Returns the tangential stiffness matrix, the internal nodal force,
        the strain and the stress tensor (voigt-notation) of the Element.

        Parameters
        ----------
        X : ndarray
            nodal coordinates given in Voigt notation (i.e. a 1-D-Array
            of type [x_1, y_1, z_1, x_2, y_2, z_2 etc.])
        u : ndarray
            nodal displacements given in Voigt notation
        t : float
            time

        Returns
        -------
        K : ndarray
            The tangential stiffness matrix (ndarray of dimension (ndim, ndim))
        f : ndarray
            The nodal force vector (ndarray of dimension (ndim,))
        S : ndarray
            The stress tensor (ndarray of dimension (no_of_nodes, 6))
        E : ndarray
            The strain tensor (ndarray of dimension (no_of_nodes, 6))

        Examples
        --------
        TODO

        '''
        self._compute_tensors(X, u, t)
        return self.K, self.f, self.S, self.E



class Tri3(Element):
    '''
    Element class for a plane triangle element in Total Lagrangian formulation.
    The displacements are given in x- and y-coordinates;

    Notes
    -----
    The Element assumes constant strain and stress over the whole element.
    Thus the approximation quality is very moderate.


    References
    ----------
    Basis for this implementation is the Monograph of Ted Belytschko:
    Nonlinear Finite Elements for Continua and Structures.
    pp. 201 and 207.

    '''
    plane_stress = True
    name = 'Tri3'

    def __init__(self, *args, **kwargs):
        '''
        Parameters
        ----------
        material : class HyperelasticMaterial
            Material class representing the material
        '''
        super().__init__(*args, **kwargs)
        self.K = np.zeros((6,6))
        self.f = np.zeros(6)
        self.S = np.zeros((3,6))
        self.E = np.zeros((3,6))

    def _compute_tensors(self, X, u, t):
        '''
        Compute the tensors B0_tilde, B0, F, E and S at the Gauss Points.

        Variables
        ---------
            B0_tilde: ndarray
                Die Ableitung der Ansatzfunktionen nach den x- und
                y-Koordinaten (2x3-Matrix). In den Zeilein stehen die
                Koordinatenrichtungen, in den Spalten die Ansatzfunktionen
            B0: ndarray
                The mapping matrix of delta E = B0 * u^e
            F: ndarray
                Deformation gradient (2x2-Matrix)
            E: ndarray
                Der Green-Lagrange strain tensor (2x2-Matrix)
            S: ndarray
                2. Piola-Kirchhoff stress tensor, using Kirchhoff material
                (2x2-Matrix)
        '''
        d = self.material.thickness
        X1, Y1, X2, Y2, X3, Y3 = X
        u_mat = u.reshape((-1,2))
        det = (X3-X2)*(Y1-Y2) - (X1-X2)*(Y3-Y2)
        A0       = 0.5*det
        dN_dX = 1/det*np.array([[Y2-Y3, X3-X2], [Y3-Y1, X1-X3], [Y1-Y2, X2-X1]])
        H = u_mat.T @ dN_dX
        F = H + np.eye(2)
        E = 1/2*(H + H.T + H.T @ H)
        S, S_v, C_SE = self.material.S_Sv_and_C_2d(E)
        B0 = compute_B_matrix(dN_dX, F)
        K_geo_small = dN_dX @ S @ dN_dX.T * det/2 * d
        K_geo = scatter_matrix(K_geo_small, 2)
        K_mat = B0.T @ C_SE @ B0 * det/2 * d
        self.K = (K_geo + K_mat)
        self.f = B0.T @ S_v * det/2 * d
        self.E = np.ones((3,1)) @ np.array([[E[0,0], E[0,1], 0, E[1,1], 0, 0]])
        self.S = np.ones((3,1)) @ np.array([[S[0,0], S[0,1], 0, S[1,1], 0, 0]])
        return

    def _m_int(self, X, u, t=0):
        '''
        Compute the mass matrix.

        Parameters
        ----------

        X : ndarray
            Position of the nodal coordinates in undeformed configuration
            using voigt notation X = (X1, Y1, X2, Y2, X3, Y3)
        u : ndarray
            Displacement of the element using same voigt notation as for X
        t : float
            Time

        Returns
        -------

        M : ndarray
            Mass matrix of the given element
        '''
        t = self.material.thickness
        rho = self.material.rho
        X1, Y1, X2, Y2, X3, Y3 = X
        self.A0 = 0.5*((X3-X2)*(Y1-Y2) - (X1-X2)*(Y3-Y2))
        self.M = np.array([[2, 0, 1, 0, 1, 0],
                           [0, 2, 0, 1, 0, 1],
                           [1, 0, 2, 0, 1, 0],
                           [0, 1, 0, 2, 0, 1],
                           [1, 0, 1, 0, 2, 0],
                           [0, 1, 0, 1, 0, 2]])*self.A0/12*t*rho
        return self.M


class Tri6(Element):
    '''
    6 node second order triangle
    Triangle Element with 6 dofs; 3 dofs at the corner, 3 dofs in the
    intermediate point of every face.
    '''
    plane_stress = True
    name = 'Tri6'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.K = np.zeros((12,12))
        self.f = np.zeros(12)
        self.M_small = np.zeros((6,6))
        self.M = np.zeros((12,12))
        self.S = np.zeros((6,6))
        self.E = np.zeros((6,6))

        self.gauss_points2 = ((2/3, 1/6, 1/6, 1/3),
                              (1/6, 2/3, 1/6, 1/3),
                              (1/6, 1/6, 2/3, 1/3))

        self.extrapolation_points = np.array([
            [5/3, -1/3, -1/3, 2/3, -1/3, 2/3],
            [-1/3, 5/3, -1/3, 2/3, 2/3, -1/3],
            [-1/3, -1/3, 5/3, -1/3, 2/3, 2/3]]).T

#        self.gauss_points3 = ((1/3, 1/3, 1/3, -27/48),
#                              (0.6, 0.2, 0.2, 25/48),
#                              (0.2, 0.6, 0.2, 25/48),
#                              (0.2, 0.2, 0.6, 25/48))
#
#        alpha1 = 0.0597158717
#        beta1 = 0.4701420641 # 1/(np.sqrt(15)-6)
#        w1 = 0.1323941527
#
#        alpha2 = 0.7974269853 #
#        beta2 = 0.1012865073 # 1/(np.sqrt(15)+6)
#        w2 = 0.1259391805
#
#        self.gauss_points5 = ((1/3, 1/3, 1/3, 0.225),
#                              (alpha1, beta1, beta1, w1),
#                              (beta1, alpha1, beta1, w1),
#                              (beta1, beta1, alpha1, w1),
#                              (alpha2, beta2, beta2, w2),
#                              (beta2, alpha2, beta2, w2),
#                              (beta2, beta2, alpha2, w2))

        self.gauss_points = self.gauss_points2

    def _compute_tensors(self, X, u, t):
        '''
        Tensor computation the same way as in the Tri3 element
        '''
        X1, Y1, X2, Y2, X3, Y3, X4, Y4, X5, Y5, X6, Y6 = X
        u_mat = u.reshape((-1,2))
        # X_mat = X.reshape((-1,2))
        d = self.material.thickness

        self.K *= 0
        self.f *= 0
        self.E *= 0
        self.S *= 0
        for n_gauss, (L1, L2, L3, w) in enumerate(self.gauss_points):

            dN_dL = np.array([  [4*L1 - 1,        0,        0],
                                [       0, 4*L2 - 1,        0],
                                [       0,        0, 4*L3 - 1],
                                [    4*L2,     4*L1,        0],
                                [       0,     4*L3,     4*L2],
                                [    4*L3,        0,     4*L1]])

            # the entries in the jacobian dX_dL
            Jx1 = 4*L2*X4 + 4*L3*X6 + X1*(4*L1 - 1)
            Jx2 = 4*L1*X4 + 4*L3*X5 + X2*(4*L2 - 1)
            Jx3 = 4*L1*X6 + 4*L2*X5 + X3*(4*L3 - 1)
            Jy1 = 4*L2*Y4 + 4*L3*Y6 + Y1*(4*L1 - 1)
            Jy2 = 4*L1*Y4 + 4*L3*Y5 + Y2*(4*L2 - 1)
            Jy3 = 4*L1*Y6 + 4*L2*Y5 + Y3*(4*L3 - 1)

            det = Jx1*Jy2 - Jx1*Jy3 - Jx2*Jy1 + Jx2*Jy3 + Jx3*Jy1 - Jx3*Jy2


            dL_dX = 1/det*np.array([[ Jy2 - Jy3, -Jx2 + Jx3],
                                    [-Jy1 + Jy3,  Jx1 - Jx3],
                                    [ Jy1 - Jy2, -Jx1 + Jx2]])

            B0_tilde = dN_dL @ dL_dX

            H = u_mat.T @ B0_tilde
            F = H + np.eye(2)
            E = 1/2*(H + H.T + H.T @ H)
            S, S_v, C_SE = self.material.S_Sv_and_C_2d(E)
            B0 = compute_B_matrix(B0_tilde, F)
            K_geo_small = B0_tilde @ S @ B0_tilde.T * det / 2 * d
            K_geo = scatter_matrix(K_geo_small, 2)
            K_mat = B0.T @ C_SE @ B0 * det / 2 * d
            self.K += (K_geo + K_mat) * w
            self.f += B0.T @ S_v * det / 2*d*w
            # extrapolation of gauss element
            extrapol = self.extrapolation_points[:,n_gauss:n_gauss+1]
            self.S += extrapol @ np.array([[S[0,0], S[0,1], 0, S[1,1], 0, 0]])
            self.E += extrapol @ np.array([[E[0,0], E[0,1], 0, E[1,1], 0, 0]])
        return

    def _m_int(self, X, u, t=0):
        X1, Y1, X2, Y2, X3, Y3, X4, Y4, X5, Y5, X6, Y6 = X
        t = self.material.thickness
        rho = self.material.rho
        self.M_small *= 0
        for L1, L2, L3, w in self.gauss_points:

            # the entries in the jacobian dX_dL
            Jx1 = 4*L2*X4 + 4*L3*X6 + X1*(4*L1 - 1)
            Jx2 = 4*L1*X4 + 4*L3*X5 + X2*(4*L2 - 1)
            Jx3 = 4*L1*X6 + 4*L2*X5 + X3*(4*L3 - 1)
            Jy1 = 4*L2*Y4 + 4*L3*Y6 + Y1*(4*L1 - 1)
            Jy2 = 4*L1*Y4 + 4*L3*Y5 + Y2*(4*L2 - 1)
            Jy3 = 4*L1*Y6 + 4*L2*Y5 + Y3*(4*L3 - 1)

            det = Jx1*Jy2 - Jx1*Jy3 - Jx2*Jy1 + Jx2*Jy3 + Jx3*Jy1 - Jx3*Jy2

            N = np.array([  [L1*(2*L1 - 1)],
                            [L2*(2*L2 - 1)],
                            [L3*(2*L3 - 1)],
                            [      4*L1*L2],
                            [      4*L2*L3],
                            [      4*L1*L3]])

            self.M_small += N.dot(N.T) * det/2 * rho * t * w

        self.M = scatter_matrix(self.M_small, 2)
        return self.M


class Quad4(Element):
    '''
    Quadrilateral 2D element with bilinear shape functions.

    .. code::

                ^ eta
        4       |       3
          o_____|_____o
          |     |     |
          |     |     |
        --------+---------->
          |     |     |   xi
          |     |     |
          o_____|_____o
        1       |       2

    '''
    name = 'Quad4'

    def __init__(self, *args, **kwargs):
        '''
        Definition of material properties and thickness as they are 2D-Elements.
        '''
        super().__init__(*args, **kwargs)
        self.K = np.zeros((8,8))
        self.f = np.zeros(8)
        self.M_small = np.zeros((4,4))
        self.M = np.zeros((8,8))
        self.S = np.zeros((4,6))
        self.E = np.zeros((4,6))

        # Gauss-Point-Handling:
        g1 = 1/np.sqrt(3)

        # Tupel for enumerator (xi, eta, weight)
        self.gauss_points = ((-g1, -g1, 1.),
                             ( g1, -g1, 1.),
                             ( g1,  g1, 1.),
                             (-g1,  g1, 1.))

        self.extrapolation_points = np.array([
            [1+np.sqrt(3)/2, -1/2, 1-np.sqrt(3)/2, -1/2],
            [-1/2, 1+np.sqrt(3)/2, -1/2, 1-np.sqrt(3)/2],
            [1-np.sqrt(3)/2, -1/2, 1+np.sqrt(3)/2, -1/2],
            [-1/2, 1-np.sqrt(3)/2, -1/2, 1+np.sqrt(3)/2]]).T


    def _compute_tensors(self, X, u, t):
        '''
        Compute the tensors.
        '''
        X_mat = X.reshape(-1, 2)
        u_e = u.reshape(-1, 2)
        t = self.material.thickness

        # Empty former values because they are properties and a new calculation
        # for another element or displacement than before is called
        self.K *= 0
        self.f *= 0
        self.S *= 0
        self.E *= 0

        for n_gauss, (xi, eta, w) in enumerate(self.gauss_points):

            dN_dxi = np.array([ [ eta/4 - 1/4,  xi/4 - 1/4],
                                [-eta/4 + 1/4, -xi/4 - 1/4],
                                [ eta/4 + 1/4,  xi/4 + 1/4],
                                [-eta/4 - 1/4, -xi/4 + 1/4]])

            dX_dxi = X_mat.T @ dN_dxi
            det = dX_dxi[0,0]*dX_dxi[1,1] - dX_dxi[1,0]*dX_dxi[0,1]
            dxi_dX = 1/det * np.array([[ dX_dxi[1,1], -dX_dxi[0,1]],
                                       [-dX_dxi[1,0],  dX_dxi[0,0]]])

            B0_tilde = dN_dxi @ dxi_dX
            H = u_e.T @ B0_tilde
            F = H + np.eye(2)
            E = 1/2*(H + H.T + H.T @ H)
            S, S_v, C_SE = self.material.S_Sv_and_C_2d(E)
            B0 = compute_B_matrix(B0_tilde, F)
            K_geo_small = B0_tilde @ S @ B0_tilde.T * det*t
            K_geo = scatter_matrix(K_geo_small, 2)
            K_mat = B0.T @ C_SE @ B0 *det*t
            self.K += (K_geo + K_mat)*w
            self.f += B0.T @ S_v*det*t*w
            # extrapolation of gauss element
            extrapol = self.extrapolation_points[:,n_gauss:n_gauss+1]
            self.S += extrapol @ np.array([[S[0,0], S[0,1], 0, S[1,1], 0, 0]])
            self.E += extrapol @ np.array([[E[0,0], E[0,1], 0, E[1,1], 0, 0]])
        return

    def _m_int(self, X, u, t=0):
        X1, Y1, X2, Y2, X3, Y3, X4, Y4 = X
        self.M_small *= 0
        t = self.material.thickness
        rho = self.material.rho

        for xi, eta, w in self.gauss_points:
            det = 1/8*(- X1*Y2*eta + X1*Y2 + X1*Y3*eta - X1*Y3*xi + X1*Y4*xi
                       - X1*Y4 + X2*Y1*eta - X2*Y1 + X2*Y3*xi + X2*Y3
                       - X2*Y4*eta - X2*Y4*xi - X3*Y1*eta + X3*Y1*xi
                       - X3*Y2*xi - X3*Y2 + X3*Y4*eta + X3*Y4 - X4*Y1*xi
                       + X4*Y1 + X4*Y2*eta + X4*Y2*xi - X4*Y3*eta - X4*Y3)
            N = np.array([  [(-eta + 1)*(-xi + 1)/4],
                            [ (-eta + 1)*(xi + 1)/4],
                            [  (eta + 1)*(xi + 1)/4],
                            [ (eta + 1)*(-xi + 1)/4]])
            self.M_small += N.dot(N.T) * det * rho * t * w

        self.M = scatter_matrix(self.M_small, 2)
        return self.M


class Quad8(Element):
    '''
    Plane Quadrangle with quadratic shape functions and 8 nodes. 4 nodes are
    at every corner, 4 nodes on every face.
    '''
    name = 'Quad8'

    def __init__(self, *args, **kwargs):
        '''
        Definition of material properties and thickness as they are 2D-Elements.
        '''
        super().__init__(*args, **kwargs)
        self.K = np.zeros((16,16))
        self.f = np.zeros(16)
        self.M_small = np.zeros((8,8))
        self.M = np.zeros((16,16))
        self.S = np.zeros((8,6))
        self.E = np.zeros((8,6))

        # Quadrature like ANSYS or ABAQUS:
        g = np.sqrt(3/5)
        w = 5/9
        w0 = 8/9
        self.gauss_points = ((-g, -g,  w*w), ( g, -g,  w*w ), ( g,  g,   w*w),
                             (-g,  g,  w*w), ( 0, -g, w0*w ), ( g,  0,  w*w0),
                             ( 0,  g, w0*w), (-g,  0,  w*w0), ( 0,  0, w0*w0))

        # a little bit dirty but correct. Comes from sympy file.
        self.extrapolation_points = np.array(
        [[ 5*sqrt(15)/18 + 10/9, 5/18, -5*sqrt(15)/18 + 10/9,
            5/18, -5/9 - sqrt(15)/9, -5/9 + sqrt(15)/9,
            -5/9 + sqrt(15)/9, -5/9 - sqrt(15)/9,  4/9],
         [5/18,  5*sqrt(15)/18 + 10/9, 5/18, -5*sqrt(15)/18 + 10/9,
          -5/9 - sqrt(15)/9, -5/9 - sqrt(15)/9, -5/9 + sqrt(15)/9,
          -5/9 + sqrt(15)/9,  4/9],
         [-5*sqrt(15)/18 + 10/9, 5/18, 5*sqrt(15)/18 + 10/9, 5/18,
          -5/9 + sqrt(15)/9, -5/9 - sqrt(15)/9, -5/9 - sqrt(15)/9,
          -5/9 + sqrt(15)/9,  4/9],
         [ 5/18, -5*sqrt(15)/18 + 10/9, 5/18,  5*sqrt(15)/18 + 10/9,
          -5/9 + sqrt(15)/9, -5/9 + sqrt(15)/9, -5/9 - sqrt(15)/9,
          -5/9 - sqrt(15)/9,  4/9],
         [ 0,  0,  0,  0, sqrt(15)/6 + 5/6,  0, -sqrt(15)/6 + 5/6,  0, -2/3],
         [0, 0, 0, 0, 0, sqrt(15)/6 + 5/6,  0, -sqrt(15)/6 + 5/6, -2/3],
         [ 0, 0, 0, 0, -sqrt(15)/6 + 5/6, 0, sqrt(15)/6 + 5/6, 0, -2/3],
         [ 0, 0, 0, 0, 0, -sqrt(15)/6 + 5/6, 0, sqrt(15)/6 + 5/6, -2/3]])

    def _compute_tensors(self, X, u, t):
#        X1, Y1, X2, Y2, X3, Y3, X4, Y4, X5, Y5, X6, Y6, X7, Y7, X8, Y8 = X
        X_mat = X.reshape(-1, 2)
        u_e = u.reshape(-1, 2)
        t = self.material.thickness


        self.K *= 0
        self.f *= 0
        self.S *= 0
        self.E *= 0

        for n_gauss, (xi, eta, w) in enumerate(self.gauss_points):
            # this is now the standard procedure for Total Lagrangian behavior
            dN_dxi = np.array([
                [-(eta - 1)*(eta + 2*xi)/4, -(2*eta + xi)*(xi - 1)/4],
                [ (eta - 1)*(eta - 2*xi)/4,  (2*eta - xi)*(xi + 1)/4],
                [ (eta + 1)*(eta + 2*xi)/4,  (2*eta + xi)*(xi + 1)/4],
                [-(eta + 1)*(eta - 2*xi)/4, -(2*eta - xi)*(xi - 1)/4],
                [             xi*(eta - 1),            xi**2/2 - 1/2],
                [          -eta**2/2 + 1/2,            -eta*(xi + 1)],
                [            -xi*(eta + 1),           -xi**2/2 + 1/2],
                [           eta**2/2 - 1/2,             eta*(xi - 1)]])
            dX_dxi = X_mat.T @ dN_dxi
            det = dX_dxi[0,0]*dX_dxi[1,1] - dX_dxi[1,0]*dX_dxi[0,1]
            dxi_dX = 1/det*np.array([[ dX_dxi[1,1], -dX_dxi[0,1]],
                                     [-dX_dxi[1,0],  dX_dxi[0,0]]])

            B0_tilde = dN_dxi @ dxi_dX
            H = u_e.T @ B0_tilde
            F = H + np.eye(2)
            E = 1/2*(H + H.T + H.T @ H)
            S, S_v, C_SE = self.material.S_Sv_and_C_2d(E)
            B0 = compute_B_matrix(B0_tilde, F)
            K_geo_small = B0_tilde @ S @ B0_tilde.T * det*t
            K_geo = scatter_matrix(K_geo_small, 2)
            K_mat = B0.T @ C_SE @ B0 * det * t
            self.K += w*(K_geo + K_mat)
            self.f += B0.T @ S_v*det*t*w
            # extrapolation of gauss element
            extrapol = self.extrapolation_points[:,n_gauss:n_gauss+1]
            self.S += extrapol @ np.array([[S[0,0], S[0,1], 0, S[1,1], 0, 0]])
            self.E += extrapol @ np.array([[E[0,0], E[0,1], 0, E[1,1], 0, 0]])
        return

    def _m_int(self, X, u, t=0):
        '''
        Mass matrix using CAS-System
        '''
        X_mat = X.reshape(-1, 2)
        t = self.material.thickness
        rho = self.material.rho

        self.M_small *= 0

        for xi, eta, w in self.gauss_points:
            N = np.array([  [(-eta + 1)*(-xi + 1)*(-eta - xi - 1)/4],
                            [ (-eta + 1)*(xi + 1)*(-eta + xi - 1)/4],
                            [   (eta + 1)*(xi + 1)*(eta + xi - 1)/4],
                            [  (eta + 1)*(-xi + 1)*(eta - xi - 1)/4],
                            [             (-eta + 1)*(-xi**2 + 1)/2],
                            [              (-eta**2 + 1)*(xi + 1)/2],
                            [              (eta + 1)*(-xi**2 + 1)/2],
                            [             (-eta**2 + 1)*(-xi + 1)/2]])

            dN_dxi = np.array([
                [-(eta - 1)*(eta + 2*xi)/4, -(2*eta + xi)*(xi - 1)/4],
                [ (eta - 1)*(eta - 2*xi)/4,  (2*eta - xi)*(xi + 1)/4],
                [ (eta + 1)*(eta + 2*xi)/4,  (2*eta + xi)*(xi + 1)/4],
                [-(eta + 1)*(eta - 2*xi)/4, -(2*eta - xi)*(xi - 1)/4],
                [             xi*(eta - 1),            xi**2/2 - 1/2],
                [          -eta**2/2 + 1/2,            -eta*(xi + 1)],
                [            -xi*(eta + 1),           -xi**2/2 + 1/2],
                [           eta**2/2 - 1/2,             eta*(xi - 1)]])
            dX_dxi = X_mat.T @ dN_dxi
            det = dX_dxi[0,0]*dX_dxi[1,1] - dX_dxi[1,0]*dX_dxi[0,1]
            self.M_small += N @ N.T * det * rho * t * w

        self.M = scatter_matrix(self.M_small, 2)
        return self.M


class Tet4(Element):
    '''
    Tetraeder-Element with 4 nodes
    '''
    name = 'Tet4'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.K = np.zeros((12,12))
        self.f = np.zeros(12)
        self.M = np.zeros((12,12))
        self.S = np.zeros((4,6))
        self.E = np.zeros((4,6))


    def _compute_tensors(self, X, u, t):
        X1, Y1, Z1, X2, Y2, Z2, X3, Y3, Z3, X4, Y4, Z4 = X
        u_mat = u.reshape(-1, 3)
        X_mat = X.reshape(-1, 3)

        det = -X1*Y2*Z3 + X1*Y2*Z4 + X1*Y3*Z2 - X1*Y3*Z4 - X1*Y4*Z2 + X1*Y4*Z3 \
             + X2*Y1*Z3 - X2*Y1*Z4 - X2*Y3*Z1 + X2*Y3*Z4 + X2*Y4*Z1 - X2*Y4*Z3 \
             - X3*Y1*Z2 + X3*Y1*Z4 + X3*Y2*Z1 - X3*Y2*Z4 - X3*Y4*Z1 + X3*Y4*Z2 \
             + X4*Y1*Z2 - X4*Y1*Z3 - X4*Y2*Z1 + X4*Y2*Z3 + X4*Y3*Z1 - X4*Y3*Z2

        B0_tilde = 1/det*np.array([
            [-Y2*Z3 + Y2*Z4 + Y3*Z2 - Y3*Z4 - Y4*Z2 + Y4*Z3,
              X2*Z3 - X2*Z4 - X3*Z2 + X3*Z4 + X4*Z2 - X4*Z3,
             -X2*Y3 + X2*Y4 + X3*Y2 - X3*Y4 - X4*Y2 + X4*Y3],
            [ Y1*Z3 - Y1*Z4 - Y3*Z1 + Y3*Z4 + Y4*Z1 - Y4*Z3,
             -X1*Z3 + X1*Z4 + X3*Z1 - X3*Z4 - X4*Z1 + X4*Z3,
              X1*Y3 - X1*Y4 - X3*Y1 + X3*Y4 + X4*Y1 - X4*Y3],
            [-Y1*Z2 + Y1*Z4 + Y2*Z1 - Y2*Z4 - Y4*Z1 + Y4*Z2,
              X1*Z2 - X1*Z4 - X2*Z1 + X2*Z4 + X4*Z1 - X4*Z2,
             -X1*Y2 + X1*Y4 + X2*Y1 - X2*Y4 - X4*Y1 + X4*Y2],
            [ Y1*Z2 - Y1*Z3 - Y2*Z1 + Y2*Z3 + Y3*Z1 - Y3*Z2,
             -X1*Z2 + X1*Z3 + X2*Z1 - X2*Z3 - X3*Z1 + X3*Z2,
              X1*Y2 - X1*Y3 - X2*Y1 + X2*Y3 + X3*Y1 - X3*Y2]])

        H = u_mat.T @ B0_tilde
        F = H + np.eye(3)
        E = 1/2*(H + H.T + H.T @ H)
        S, S_v, C_SE = self.material.S_Sv_and_C(E)
        B0 = compute_B_matrix(B0_tilde, F)
        K_geo_small = B0_tilde @ S @ B0_tilde.T * det/6
        K_geo = scatter_matrix(K_geo_small, 3)
        K_mat = B0.T @ C_SE @ B0 * det/6
        self.K = K_geo + K_mat
        self.f = B0.T @ S_v*det/6
        self.E = np.ones((4,1)) @ np.array([[E[0,0], E[0,1], E[0,2],
                                             E[1,1], E[1,2], E[2,2]]])
        self.S = np.ones((4,1)) @ np.array([[S[0,0], S[0,1], S[0,2],
                                             S[1,1], S[1,2], S[2,2]]])



    def _m_int(self, X, u, t=0):
        '''
        Mass matrix using CAS-System
        '''
        rho = self.material.rho

        X1, Y1, Z1, X2, Y2, Z2, X3, Y3, Z3, X4, Y4, Z4 = X
        det =   X1*Y2*Z3 - X1*Y2*Z4 - X1*Y3*Z2 + X1*Y3*Z4 + X1*Y4*Z2 - X1*Y4*Z3 \
              - X2*Y1*Z3 + X2*Y1*Z4 + X2*Y3*Z1 - X2*Y3*Z4 - X2*Y4*Z1 + X2*Y4*Z3 \
              + X3*Y1*Z2 - X3*Y1*Z4 - X3*Y2*Z1 + X3*Y2*Z4 + X3*Y4*Z1 - X3*Y4*Z2 \
              - X4*Y1*Z2 + X4*Y1*Z3 + X4*Y2*Z1 - X4*Y2*Z3 - X4*Y3*Z1 + X4*Y3*Z2

        # same thing as above - it's not clear yet how the node numbering is done.
        det *= -1
        V = det/6
        self.M = V / 20 * rho * np.array([
            [ 2.,  0.,  0.,  1.,  0.,  0.,  1.,  0.,  0.,  1.,  0.,  0.],
            [ 0.,  2.,  0.,  0.,  1.,  0.,  0.,  1.,  0.,  0.,  1.,  0.],
            [ 0.,  0.,  2.,  0.,  0.,  1.,  0.,  0.,  1.,  0.,  0.,  1.],
            [ 1.,  0.,  0.,  2.,  0.,  0.,  1.,  0.,  0.,  1.,  0.,  0.],
            [ 0.,  1.,  0.,  0.,  2.,  0.,  0.,  1.,  0.,  0.,  1.,  0.],
            [ 0.,  0.,  1.,  0.,  0.,  2.,  0.,  0.,  1.,  0.,  0.,  1.],
            [ 1.,  0.,  0.,  1.,  0.,  0.,  2.,  0.,  0.,  1.,  0.,  0.],
            [ 0.,  1.,  0.,  0.,  1.,  0.,  0.,  2.,  0.,  0.,  1.,  0.],
            [ 0.,  0.,  1.,  0.,  0.,  1.,  0.,  0.,  2.,  0.,  0.,  1.],
            [ 1.,  0.,  0.,  1.,  0.,  0.,  1.,  0.,  0.,  2.,  0.,  0.],
            [ 0.,  1.,  0.,  0.,  1.,  0.,  0.,  1.,  0.,  0.,  2.,  0.],
            [ 0.,  0.,  1.,  0.,  0.,  1.,  0.,  0.,  1.,  0.,  0.,  2.]])
        return self.M



class Tet10(Element):
    r'''
    Tet10 solid element; Node numbering is done like in ParaView and in [1]_

    The node numbering is as follows:

    .. code::
                 3
               ,/|`\
             ,/  |  `\
           ,8    '.   `7
         ,/       9     `\
       ,/         |       `\
      1--------4--'.--------0
       `\.         |      ,/
          `\.      |    ,6
             `5.   '. ,/
                `\. |/
                   `2

    References
    ----------
    .. [1] Felippa, Carlos: Advanced Finite Element Methods (ASEN 6367),
        Spring 2013. `Online Source`__

    __ http://www.colorado.edu/engineering/CAS/courses.d/AFEM.d/AFEM.Ch10.d/
        AFEM.Ch10.index.html

    '''
    name = 'Tet10'

    def __init__(self, *args, **kwargs):
        '''
        '''
        super().__init__(*args, **kwargs)

        self.K = np.zeros((30,30))
        self.f = np.zeros(30)
        self.M = np.zeros((30,30))
        self.S = np.zeros((10,6))
        self.E = np.zeros((10,6))


        a = (5 - np.sqrt(5)) / 20
        b = (5 + 3*np.sqrt(5)) / 20
        w = 1/4
        gauss_points_4 = ((b,a,a,a,w),
                          (a,b,a,a,w),
                          (a,a,b,a,w),
                          (a,a,a,b,w),)
        self.gauss_points = gauss_points_4

        c1 = 1/4 + 3*sqrt(5)/4 # close corner node
        c2 = -sqrt(5)/4 + 1/4  # far corner node
        m1 = 1/4 + sqrt(5)/4   # close mid-node
        m2 = -sqrt(5)/4 + 1/4  # far mid node

        self.extrapolation_points = np.array(
            [[c1, c2, c2, c2, m1, m2, m1, m1, m2, m2],
             [c2, c1, c2, c2, m1, m1, m2, m2, m1, m2],
             [c2, c2, c1, c2, m2, m1, m1, m2, m2, m1],
             [c2, c2, c2, c1, m2, m2, m2, m1, m1, m1]]).T


    def _compute_tensors(self, X, u, t):

        X1, Y1, Z1, \
        X2, Y2, Z2, \
        X3, Y3, Z3, \
        X4, Y4, Z4, \
        X5, Y5, Z5, \
        X6, Y6, Z6, \
        X7, Y7, Z7, \
        X8, Y8, Z8, \
        X9, Y9, Z9, \
        X10, Y10, Z10 = X

        u_mat = u.reshape((10,3))
        self.K *= 0
        self.f *= 0
        self.S *= 0
        self.E *= 0

        for n_gauss, (L1, L2, L3, L4, w) in enumerate(self.gauss_points):

            Jx1 = 4*L2*X5 + 4*L3*X7 + 4*L4*X8  + X1*(4*L1 - 1)
            Jx2 = 4*L1*X5 + 4*L3*X6 + 4*L4*X9  + X2*(4*L2 - 1)
            Jx3 = 4*L1*X7 + 4*L2*X6 + 4*L4*X10 + X3*(4*L3 - 1)
            Jx4 = 4*L1*X8 + 4*L2*X9 + 4*L3*X10 + X4*(4*L4 - 1)
            Jy1 = 4*L2*Y5 + 4*L3*Y7 + 4*L4*Y8  + Y1*(4*L1 - 1)
            Jy2 = 4*L1*Y5 + 4*L3*Y6 + 4*L4*Y9  + Y2*(4*L2 - 1)
            Jy3 = 4*L1*Y7 + 4*L2*Y6 + 4*L4*Y10 + Y3*(4*L3 - 1)
            Jy4 = 4*L1*Y8 + 4*L2*Y9 + 4*L3*Y10 + Y4*(4*L4 - 1)
            Jz1 = 4*L2*Z5 + 4*L3*Z7 + 4*L4*Z8  + Z1*(4*L1 - 1)
            Jz2 = 4*L1*Z5 + 4*L3*Z6 + 4*L4*Z9  + Z2*(4*L2 - 1)
            Jz3 = 4*L1*Z7 + 4*L2*Z6 + 4*L4*Z10 + Z3*(4*L3 - 1)
            Jz4 = 4*L1*Z8 + 4*L2*Z9 + 4*L3*Z10 + Z4*(4*L4 - 1)

            det = -Jx1*Jy2*Jz3 + Jx1*Jy2*Jz4 + Jx1*Jy3*Jz2 - Jx1*Jy3*Jz4 \
                 - Jx1*Jy4*Jz2 + Jx1*Jy4*Jz3 + Jx2*Jy1*Jz3 - Jx2*Jy1*Jz4 \
                 - Jx2*Jy3*Jz1 + Jx2*Jy3*Jz4 + Jx2*Jy4*Jz1 - Jx2*Jy4*Jz3 \
                 - Jx3*Jy1*Jz2 + Jx3*Jy1*Jz4 + Jx3*Jy2*Jz1 - Jx3*Jy2*Jz4 \
                 - Jx3*Jy4*Jz1 + Jx3*Jy4*Jz2 + Jx4*Jy1*Jz2 - Jx4*Jy1*Jz3 \
                 - Jx4*Jy2*Jz1 + Jx4*Jy2*Jz3 + Jx4*Jy3*Jz1 - Jx4*Jy3*Jz2

            a1 = -Jy2*Jz3 + Jy2*Jz4 + Jy3*Jz2 - Jy3*Jz4 - Jy4*Jz2 + Jy4*Jz3
            a2 =  Jy1*Jz3 - Jy1*Jz4 - Jy3*Jz1 + Jy3*Jz4 + Jy4*Jz1 - Jy4*Jz3
            a3 = -Jy1*Jz2 + Jy1*Jz4 + Jy2*Jz1 - Jy2*Jz4 - Jy4*Jz1 + Jy4*Jz2
            a4 =  Jy1*Jz2 - Jy1*Jz3 - Jy2*Jz1 + Jy2*Jz3 + Jy3*Jz1 - Jy3*Jz2
            b1 =  Jx2*Jz3 - Jx2*Jz4 - Jx3*Jz2 + Jx3*Jz4 + Jx4*Jz2 - Jx4*Jz3
            b2 = -Jx1*Jz3 + Jx1*Jz4 + Jx3*Jz1 - Jx3*Jz4 - Jx4*Jz1 + Jx4*Jz3
            b3 =  Jx1*Jz2 - Jx1*Jz4 - Jx2*Jz1 + Jx2*Jz4 + Jx4*Jz1 - Jx4*Jz2
            b4 = -Jx1*Jz2 + Jx1*Jz3 + Jx2*Jz1 - Jx2*Jz3 - Jx3*Jz1 + Jx3*Jz2
            c1 = -Jx2*Jy3 + Jx2*Jy4 + Jx3*Jy2 - Jx3*Jy4 - Jx4*Jy2 + Jx4*Jy3
            c2 =  Jx1*Jy3 - Jx1*Jy4 - Jx3*Jy1 + Jx3*Jy4 + Jx4*Jy1 - Jx4*Jy3
            c3 = -Jx1*Jy2 + Jx1*Jy4 + Jx2*Jy1 - Jx2*Jy4 - Jx4*Jy1 + Jx4*Jy2
            c4 =  Jx1*Jy2 - Jx1*Jy3 - Jx2*Jy1 + Jx2*Jy3 + Jx3*Jy1 - Jx3*Jy2

            B0_tilde = 1/det*np.array([
                [    a1*(4*L1 - 1),     b1*(4*L1 - 1),     c1*(4*L1 - 1)],
                [    a2*(4*L2 - 1),     b2*(4*L2 - 1),     c2*(4*L2 - 1)],
                [    a3*(4*L3 - 1),     b3*(4*L3 - 1),     c3*(4*L3 - 1)],
                [    a4*(4*L4 - 1),     b4*(4*L4 - 1),     c4*(4*L4 - 1)],
                [4*L1*a2 + 4*L2*a1, 4*L1*b2 + 4*L2*b1, 4*L1*c2 + 4*L2*c1],
                [4*L2*a3 + 4*L3*a2, 4*L2*b3 + 4*L3*b2, 4*L2*c3 + 4*L3*c2],
                [4*L1*a3 + 4*L3*a1, 4*L1*b3 + 4*L3*b1, 4*L1*c3 + 4*L3*c1],
                [4*L1*a4 + 4*L4*a1, 4*L1*b4 + 4*L4*b1, 4*L1*c4 + 4*L4*c1],
                [4*L2*a4 + 4*L4*a2, 4*L2*b4 + 4*L4*b2, 4*L2*c4 + 4*L4*c2],
                [4*L3*a4 + 4*L4*a3, 4*L3*b4 + 4*L4*b3, 4*L3*c4 + 4*L4*c3]])

            H = u_mat.T @ B0_tilde
            F = H + np.eye(3)
            E = 1/2*(H + H.T + H.T @ H)
            S, S_v, C_SE = self.material.S_Sv_and_C(E)
            B0 = compute_B_matrix(B0_tilde, F)
            K_geo_small = B0_tilde @ S @ B0_tilde.T * det/6
            K_geo = scatter_matrix(K_geo_small, 3)
            K_mat = B0.T @ C_SE @ B0 * det/6

            self.K += (K_geo + K_mat) * w
            self.f += B0.T @ S_v * det/6 * w

            # extrapolation of gauss element
            extrapol = self.extrapolation_points[:,n_gauss:n_gauss+1]
            self.S += extrapol @ np.array([[S[0,0], S[0,1], S[0,2],
                                            S[1,1], S[1,2], S[2,2]]])
            self.E += extrapol @ np.array([[E[0,0], E[0,1], E[0,2],
                                            E[1,1], E[1,2], E[2,2]]])
        return

    def _m_int(self, X, u, t=0):
        '''
        Mass matrix using CAS-System
        '''
        X1, Y1, Z1, \
        X2, Y2, Z2, \
        X3, Y3, Z3, \
        X4, Y4, Z4, \
        X5, Y5, Z5, \
        X6, Y6, Z6, \
        X7, Y7, Z7, \
        X8, Y8, Z8, \
        X9, Y9, Z9, \
        X10, Y10, Z10 = X
        X_mat = X.reshape((-1,3))

        self.M *= 0
        rho = self.material.rho

        for L1, L2, L3, L4, w in self.gauss_points:

            Jx1 = 4*L2*X5 + 4*L3*X7 + 4*L4*X8  + X1*(4*L1 - 1)
            Jx2 = 4*L1*X5 + 4*L3*X6 + 4*L4*X9  + X2*(4*L2 - 1)
            Jx3 = 4*L1*X7 + 4*L2*X6 + 4*L4*X10 + X3*(4*L3 - 1)
            Jx4 = 4*L1*X8 + 4*L2*X9 + 4*L3*X10 + X4*(4*L4 - 1)
            Jy1 = 4*L2*Y5 + 4*L3*Y7 + 4*L4*Y8  + Y1*(4*L1 - 1)
            Jy2 = 4*L1*Y5 + 4*L3*Y6 + 4*L4*Y9  + Y2*(4*L2 - 1)
            Jy3 = 4*L1*Y7 + 4*L2*Y6 + 4*L4*Y10 + Y3*(4*L3 - 1)
            Jy4 = 4*L1*Y8 + 4*L2*Y9 + 4*L3*Y10 + Y4*(4*L4 - 1)
            Jz1 = 4*L2*Z5 + 4*L3*Z7 + 4*L4*Z8  + Z1*(4*L1 - 1)
            Jz2 = 4*L1*Z5 + 4*L3*Z6 + 4*L4*Z9  + Z2*(4*L2 - 1)
            Jz3 = 4*L1*Z7 + 4*L2*Z6 + 4*L4*Z10 + Z3*(4*L3 - 1)
            Jz4 = 4*L1*Z8 + 4*L2*Z9 + 4*L3*Z10 + Z4*(4*L4 - 1)

            det = -Jx1*Jy2*Jz3 + Jx1*Jy2*Jz4 + Jx1*Jy3*Jz2 - Jx1*Jy3*Jz4 \
                 - Jx1*Jy4*Jz2 + Jx1*Jy4*Jz3 + Jx2*Jy1*Jz3 - Jx2*Jy1*Jz4 \
                 - Jx2*Jy3*Jz1 + Jx2*Jy3*Jz4 + Jx2*Jy4*Jz1 - Jx2*Jy4*Jz3 \
                 - Jx3*Jy1*Jz2 + Jx3*Jy1*Jz4 + Jx3*Jy2*Jz1 - Jx3*Jy2*Jz4 \
                 - Jx3*Jy4*Jz1 + Jx3*Jy4*Jz2 + Jx4*Jy1*Jz2 - Jx4*Jy1*Jz3 \
                 - Jx4*Jy2*Jz1 + Jx4*Jy2*Jz3 + Jx4*Jy3*Jz1 - Jx4*Jy3*Jz2

            N = np.array([  [L1*(2*L1 - 1)],
                            [L2*(2*L2 - 1)],
                            [L3*(2*L3 - 1)],
                            [L4*(2*L4 - 1)],
                            [      4*L1*L2],
                            [      4*L2*L3],
                            [      4*L1*L3],
                            [      4*L1*L4],
                            [      4*L2*L4],
                            [      4*L3*L4]])

            M_small = N.dot(N.T) * det/6 * rho * w
            self.M += scatter_matrix(M_small, 3)
        return self.M


class Hexa8(Element):
    '''
    Eight point Hexahedron element.

    .. code::


                 eta
        3----------2
        |\     ^   |\
        | \    |   | \
        |  \   |   |  \
        |   7------+---6
        |   |  +-- |-- | -> xi
        0---+---\--1   |
         \  |    \  \  |
          \ |     \  \ |
           \|   zeta  \|
            4----------5

    '''
    name = 'Hexa8'

    def __init__(self, *args, **kwargs):
        '''
        '''
        super().__init__(*args, **kwargs)

        self.K = np.zeros((24,24))
        self.f = np.zeros(24)
        self.M = np.zeros((24,24))
        self.S = np.zeros((8,6))
        self.E = np.zeros((8,6))

        a = np.sqrt(1/3)
        self.gauss_points = ((-a,  a,  a, 1),
                             ( a,  a,  a, 1),
                             (-a, -a,  a, 1),
                             ( a, -a,  a, 1),
                             (-a,  a, -a, 1),
                             ( a,  a, -a, 1),
                             (-a, -a, -a, 1),
                             ( a, -a, -a, 1),)

        b = (-np.sqrt(3) + 1)**2*(np.sqrt(3) + 1)/8
        c = (-np.sqrt(3) + 1)**3/8
        d = (np.sqrt(3) + 1)**3/8
        e = (np.sqrt(3) + 1)**2*(-np.sqrt(3) + 1)/8
        self.extrapolation_points = np.array([[b, c, e, b, e, b, d, e],
                                              [c, b, b, e, b, e, e, d],
                                              [b, e, c, b, e, d, b, e],
                                              [e, b, b, c, d, e, e, b],
                                              [e, b, d, e, b, c, e, b],
                                              [b, e, e, d, c, b, b, e],
                                              [e, d, b, e, b, e, c, b],
                                              [d, e, e, b, e, b, b, c]])


    def _compute_tensors(self, X, u, t):
        X_mat = X.reshape(8, 3)
        u_mat = u.reshape(8, 3)

        self.K *= 0
        self.f *= 0
        self.S *= 0
        self.E *= 0

        for n_gauss, (xi, eta, zeta, w) in enumerate(self.gauss_points):

            dN_dxi = 1/8*np.array([
                [-(-eta+1)*(-zeta+1), -(-xi+1)*(-zeta+1), -(-eta+1)*(-xi+1)],
                [ (-eta+1)*(-zeta+1),  -(xi+1)*(-zeta+1),  -(-eta+1)*(xi+1)],
                [  (eta+1)*(-zeta+1),   (xi+1)*(-zeta+1),   -(eta+1)*(xi+1)],
                [ -(eta+1)*(-zeta+1),  (-xi+1)*(-zeta+1),  -(eta+1)*(-xi+1)],
                [ -(-eta+1)*(zeta+1),  -(-xi+1)*(zeta+1),  (-eta+1)*(-xi+1)],
                [  (-eta+1)*(zeta+1),   -(xi+1)*(zeta+1),   (-eta+1)*(xi+1)],
                [   (eta+1)*(zeta+1),    (xi+1)*(zeta+1),    (eta+1)*(xi+1)],
                [  -(eta+1)*(zeta+1),   (-xi+1)*(zeta+1),   (eta+1)*(-xi+1)]])
            dX_dxi = X_mat.T @ dN_dxi
            dxi_dX = np.linalg.inv(dX_dxi)
            det = np.linalg.det(dX_dxi)
            B0_tilde = dN_dxi @ dxi_dX
            H = u_mat.T @ B0_tilde
            F = H + np.eye(3)
            E = 1/2*(H + H.T + H.T @ H)
            S, S_v, C_SE = self.material.S_Sv_and_C(E)
            B0 = compute_B_matrix(B0_tilde, F)
            K_geo_small = B0_tilde @ S @ B0_tilde.T * det
            K_geo = scatter_matrix(K_geo_small, 3)
            K_mat = B0.T @ C_SE @ B0 * det

            self.K += (K_geo + K_mat) * w
            self.f += B0.T @ S_v * det * w

            # extrapolation of gauss element
            extrapol = self.extrapolation_points[:,n_gauss:n_gauss+1]
            self.S += extrapol @ np.array([[S[0,0], S[0,1], S[0,2],
                                            S[1,1], S[1,2], S[2,2]]])
            self.E += extrapol @ np.array([[E[0,0], E[0,1], E[0,2],
                                            E[1,1], E[1,2], E[2,2]]])
        return

    def _m_int(self, X, u, t=0):
        X_mat = X.reshape(8, 3)

        self.M *= 0
        rho = self.material.rho

        for n_gauss, (xi, eta, zeta, w) in enumerate(self.gauss_points):
            N = np.array([
                            [(-eta + 1)*(-xi + 1)*(-zeta + 1)/8],
                            [ (-eta + 1)*(xi + 1)*(-zeta + 1)/8],
                            [  (eta + 1)*(xi + 1)*(-zeta + 1)/8],
                            [ (eta + 1)*(-xi + 1)*(-zeta + 1)/8],
                            [ (-eta + 1)*(-xi + 1)*(zeta + 1)/8],
                            [  (-eta + 1)*(xi + 1)*(zeta + 1)/8],
                            [   (eta + 1)*(xi + 1)*(zeta + 1)/8],
                            [  (eta + 1)*(-xi + 1)*(zeta + 1)/8]])

            dN_dxi = 1/8*np.array([
                [-(-eta+1)*(-zeta+1), -(-xi+1)*(-zeta+1), -(-eta+1)*(-xi+1)],
                [ (-eta+1)*(-zeta+1),  -(xi+1)*(-zeta+1),  -(-eta+1)*(xi+1)],
                [  (eta+1)*(-zeta+1),   (xi+1)*(-zeta+1),   -(eta+1)*(xi+1)],
                [ -(eta+1)*(-zeta+1),  (-xi+1)*(-zeta+1),  -(eta+1)*(-xi+1)],
                [ -(-eta+1)*(zeta+1),  -(-xi+1)*(zeta+1),  (-eta+1)*(-xi+1)],
                [  (-eta+1)*(zeta+1),   -(xi+1)*(zeta+1),   (-eta+1)*(xi+1)],
                [   (eta+1)*(zeta+1),    (xi+1)*(zeta+1),    (eta+1)*(xi+1)],
                [  -(eta+1)*(zeta+1),   (-xi+1)*(zeta+1),   (eta+1)*(-xi+1)]])
            dX_dxi = X_mat.T @ dN_dxi
            det = np.linalg.det(dX_dxi)

            M_small = N @ N.T * det * rho * w
            self.M += scatter_matrix(M_small, 3)

        return self.M

class Hexa20(Element):
    '''
    20-node brick element.

    .. code::
#
#       v
#3----------2            3----10----2           3----13----2
#|\     ^   |\           |\         |\          |\         |\
#| \    |   | \          | 19       | 18        |15    24  | 14
#|  \   |   |  \        11  \       9  \        9  \ 20    11 \
#|   7------+---6        |   7----14+---6       |   7----19+---6
#|   |  +-- |-- | -> u   |   |      |   |       |22 |  26  | 23|
#0---+---\--1   |        0---+-8----1   |       0---+-8----1   |
# \  |    \  \  |         \  15      \  13       \ 17    25 \  18
#  \ |     \  \ |         16 |        17|        10 |  21    12|
#   \|      w  \|           \|         \|          \|         \|
#    4----------5            4----12----5           4----16----5


    '''
    name = 'Hexa20'

    def __init__(self, *args, **kwargs):
        '''
        '''
        super().__init__(*args, **kwargs)

        self.K = np.zeros((60,60))
        self.f = np.zeros(60)
        self.M = np.zeros((60,60))
        self.S = np.zeros((20,6))
        self.E = np.zeros((20,6))

        a = np.sqrt(3/5)
        wa = 5/9
        w0 = 8/9
        self.gauss_points = ((-a, -a, -a, wa*wa*wa),
                             ( 0, -a, -a, w0*wa*wa),
                             ( a, -a, -a, wa*wa*wa),
                             (-a,  0, -a, wa*w0*wa),
                             ( 0,  0, -a, w0*w0*wa),
                             ( a,  0, -a, wa*w0*wa),
                             (-a,  a, -a, wa*wa*wa),
                             ( 0,  a, -a, w0*wa*wa),
                             ( a,  a, -a, wa*wa*wa),
                             (-a, -a,  0, wa*wa*w0),
                             ( 0, -a,  0, w0*wa*w0),
                             ( a, -a,  0, wa*wa*w0),
                             (-a,  0,  0, wa*w0*w0),
                             ( 0,  0,  0, w0*w0*w0),
                             ( a,  0,  0, wa*w0*w0),
                             (-a,  a,  0, wa*wa*w0),
                             ( 0,  a,  0, w0*wa*w0),
                             ( a,  a,  0, wa*wa*w0),
                             (-a, -a,  a, wa*wa*wa),
                             ( 0, -a,  a, w0*wa*wa),
                             ( a, -a,  a, wa*wa*wa),
                             (-a,  0,  a, wa*w0*wa),
                             ( 0,  0,  a, w0*w0*wa),
                             ( a,  0,  a, wa*w0*wa),
                             (-a,  a,  a, wa*wa*wa),
                             ( 0,  a,  a, w0*wa*wa),
                             ( a,  a,  a, wa*wa*wa),)



        b = 13*np.sqrt(15)/36 + 17/12
        c = (4 + np.sqrt(15))/9
        d = (1 + np.sqrt(15))/36
        e = (3 + np.sqrt(15))/27
        f = 1/9
        g = (1 - np.sqrt(15))/36
        h = -2/27
        i = (3 - np.sqrt(15))/27
        j = -13*np.sqrt(15)/36 + 17/12
        k = (-4 + np.sqrt(15))/9
        l = (3 + np.sqrt(15))/18
        m = np.sqrt(15)/6 + 2/3
        n = 3/18
        p = (- 3 + np.sqrt(15))/18
        q = (4 - np.sqrt(15))/6

        self.extrapolation_points = np.array([
            [b,-c,d,-c,e,f,d,f,g,-c,e,f,e,h,i,f,i,k,d,f,g,f,i,k,g,k,j],
            [d,-c,b,f,e,-c,g,f,d,f,e,-c,i,h,e,k,i,f,g,f,d,k,i,f,j,k,g],
            [g,f,d,f,e,-c,d,-c,b,k,i,f,i,h,e,f,e,-c,j,k,g,k,i,f,g,f,d],
            [d,f,g,-c,e,f,b,-c,d,f,i,k,e,h,i,-c,e,f,g,k,j,f,i,k,d,f,g],
            [d,f,g,f,i,k,g,k,j,-c,e,f,e,h,i,f,i,k,b,-c,d,-c,e,f,d,f,g],
            [g,f,d,k,i,f,j,k,g,f,e,-c,i,h,e,k,i,f,d,-c,b,f,e,-c,g,f,d],
            [j,k,g,k,i,f,g,f,d,k,i,f,i,h,e,f,e,-c,g,f,d,f,e,-c,d,-c,b],
            [g,k,j,f,i,k,d,f,g,f,i,k,e,h,i,-c,e,f,d,f,g,-c,e,f,b,-c,d],
            [l,m,l,-l,-l,-l,n,-n,n,-l,-l,-l,f,f,f,p,p,p,n,-n,n,p,p,p,-p,q,-p],
            [n,-l,l,-n,-l,m,n,-l,l,p,f,-l,p,f,-l,p,f,-l,-p,p,n,q,p,-n,-p,p,n],
            [n,-n,n,-l,-l,-l,l,m,l,p,p,p,f,f,f,-l,-l,-l,-p,q,-p,p,p,p,n,-n,n],
            [l,-l,n,m,-l,-n,l,-l,n,-l,f,p,-l,f,p,-l,f,p,n,p,-p,-n,p,q,n,p,-p],
            [n,-n,n,p,p,p,-p,q,-p,-l,-l,-l,f,f,f,p,p,p,l,m,l,-l,-l,-l,n,-n,n],
            [-p,p,n,q,p,-n,-p,p,n,p,f,-l,p,f,-l,p,f,-l,n,-l,l,-n,-l,m,n,-l,l],
            [-p,q,-p,p,p,p,n,-n,n,p,p,p,f,f,f,-l,-l,-l,n,-n,n,-l,-l,-l,l,m,l],
            [n,p,-p,-n,p,q,n,p,-p,-l,f,p,-l,f,p,-l,f,p,l,-l,n,m,-l,-n,l,-l,n],
            [l,-l,n,-l,f,p,n,p,-p,m,-l,-n,-l,f,p,-n,p,q,l,-l,n,-l,f,p,n,p,-p],
            [n,-l,l,p,f,-l,-p,p,n,-n,-l,m,p,f,-l,q,p,-n,n,-l,l,p,f,-l,-p,p,n],
            [-p,p,n,p,f,-l,n,-l,l,q,p,-n,p,f,-l,-n,-l,m,-p,p,n,p,f,-l,n,-l,l],
            [n,p,-p,-l,f,p,l,-l,n,-n,p,q,-l,f,p,m,-l,-n,n,p,-p,-l,f,p,l,-l,n]])


    def _compute_tensors(self, X, u, t):
        X_mat = X.reshape(20, 3)
        u_mat = u.reshape(20, 3)

        self.K *= 0
        self.f *= 0
        self.S *= 0
        self.E *= 0

        for n_gauss, (xi, eta, zeta, w) in enumerate(self.gauss_points):

            dN_dxi = 1/8*np.array([
                                [ (eta-1)*(zeta-1)*(eta+2*xi+zeta+1),
                                 (xi-1)*(zeta-1)*(2*eta+xi+zeta+1),
                                 (eta-1)*(xi-1)*(eta+xi+2*zeta+1)],
                                [(eta-1)*(zeta-1)*(-eta+2*xi-zeta-1),
                                 (xi+1)*(zeta-1)*(-2*eta+xi-zeta-1),
                                 (eta-1)*(xi+1)*(-eta+xi-2*zeta-1)],
                                [(eta+1)*(zeta-1)*(-eta-2*xi+zeta+1),
                                 (xi+1)*(zeta-1)*(-2*eta-xi+zeta+1),
                                 (eta+1)*(xi+1)*(-eta-xi+2*zeta+1)],
                                [ (eta+1)*(zeta-1)*(eta-2*xi-zeta-1),
                                 (xi-1)*(zeta-1)*(2*eta-xi-zeta-1),
                                 (eta+1)*(xi-1)*(eta-xi-2*zeta-1)],
                                [(eta-1)*(zeta+1)*(-eta-2*xi+zeta-1),
                                 (xi-1)*(zeta+1)*(-2*eta-xi+zeta-1),
                                 (eta-1)*(xi-1)*(-eta-xi+2*zeta-1)],
                                [ (eta-1)*(zeta+1)*(eta-2*xi-zeta+1),
                                 (xi+1)*(zeta+1)*(2*eta-xi-zeta+1),
                                 (eta-1)*(xi+1)*(eta-xi-2*zeta+1)],
                                [ (eta+1)*(zeta+1)*(eta+2*xi+zeta-1),
                                 (xi+1)*(zeta+1)*(2*eta+xi+zeta-1),
                                 (eta+1)*(xi+1)*(eta+xi+2*zeta-1)],
                                [(eta+1)*(zeta+1)*(-eta+2*xi-zeta+1),
                                 (xi-1)*(zeta+1)*(-2*eta+xi-zeta+1),
                                 (eta+1)*(xi-1)*(-eta+xi-2*zeta+1)],
                                [-4*xi*(eta-1)*(zeta-1), -2*(xi**2-1)*(zeta-1),
                                 -2*(eta-1)*(xi**2-1)],
                                [ 2*(eta**2-1)*(zeta-1), 4*eta*(xi+1)*(zeta-1),
                                 2*(eta**2-1)*(xi+1)],
                                [ 4*xi*(eta+1)*(zeta-1),  2*(xi**2-1)*(zeta-1),
                                 2*(eta+1)*(xi**2-1)],
                                [-2*(eta**2-1)*(zeta-1),-4*eta*(xi-1)*(zeta-1),
                                 -2*(eta**2-1)*(xi-1)],
                                [ 4*xi*(eta-1)*(zeta+1),  2*(xi**2-1)*(zeta+1),
                                 2*(eta-1)*(xi**2-1)],
                                [-2*(eta**2-1)*(zeta+1),-4*eta*(xi+1)*(zeta+1),
                                 -2*(eta**2-1)*(xi+1)],
                                [-4*xi*(eta+1)*(zeta+1), -2*(xi**2-1)*(zeta+1),
                                 -2*(eta+1)*(xi**2-1)],
                                [ 2*(eta**2-1)*(zeta+1), 4*eta*(xi-1)*(zeta+1),
                                 2*(eta**2-1)*(xi-1)],
                                [-2*(eta-1)*(zeta**2-1), -2*(xi-1)*(zeta**2-1),
                                 -4*zeta*(eta-1)*(xi-1)],
                                [ 2*(eta-1)*(zeta**2-1),  2*(xi+1)*(zeta**2-1),
                                 4*zeta*(eta-1)*(xi+1)],
                                [-2*(eta+1)*(zeta**2-1), -2*(xi+1)*(zeta**2-1),
                                 -4*zeta*(eta+1)*(xi+1)],
                                [ 2*(eta+1)*(zeta**2-1),  2*(xi-1)*(zeta**2-1),
                                 4*zeta*(eta+1)*(xi-1)]])

            dX_dxi = X_mat.T @ dN_dxi
            dxi_dX = np.linalg.inv(dX_dxi)
            det = np.linalg.det(dX_dxi)
            B0_tilde = dN_dxi @ dxi_dX
            H = u_mat.T @ B0_tilde
            F = H + np.eye(3)
            E = 1/2*(H + H.T + H.T @ H)
            S, S_v, C_SE = self.material.S_Sv_and_C(E)
            B0 = compute_B_matrix(B0_tilde, F)
            K_geo_small = B0_tilde @ S @ B0_tilde.T * det
            K_geo = scatter_matrix(K_geo_small, 3)
            K_mat = B0.T @ C_SE @ B0 * det

            self.K += (K_geo + K_mat) * w
            self.f += B0.T @ S_v * det * w

            # extrapolation of gauss element
            extrapol = self.extrapolation_points[:,n_gauss:n_gauss+1]
            self.S += extrapol @ np.array([[S[0,0], S[0,1], S[0,2],
                                            S[1,1], S[1,2], S[2,2]]])
            self.E += extrapol @ np.array([[E[0,0], E[0,1], E[0,2],
                                            E[1,1], E[1,2], E[2,2]]])
        return

    def _m_int(self, X, u, t=0):
        X_mat = X.reshape(20, 3)

        self.M *= 0
        rho = self.material.rho

        for n_gauss, (xi, eta, zeta, w) in enumerate(self.gauss_points):
            N = 1/8*np.array([[  (eta-1)*(xi-1)*(zeta-1)*(eta+xi+zeta+2)],
                              [ -(eta-1)*(xi+1)*(zeta-1)*(eta-xi+zeta+2)],
                              [ -(eta+1)*(xi+1)*(zeta-1)*(eta+xi-zeta-2)],
                              [-(eta+1)*(xi-1)*(zeta-1)*(-eta+xi+zeta+2)],
                              [ -(eta-1)*(xi-1)*(zeta+1)*(eta+xi-zeta+2)],
                              [  (eta-1)*(xi+1)*(zeta+1)*(eta-xi-zeta+2)],
                              [  (eta+1)*(xi+1)*(zeta+1)*(eta+xi+zeta-2)],
                              [ -(eta+1)*(xi-1)*(zeta+1)*(eta-xi+zeta-2)],
                              [            -2*(eta-1)*(xi**2-1)*(zeta-1)],
                              [             2*(eta**2-1)*(xi+1)*(zeta-1)],
                              [             2*(eta+1)*(xi**2-1)*(zeta-1)],
                              [            -2*(eta**2-1)*(xi-1)*(zeta-1)],
                              [             2*(eta-1)*(xi**2-1)*(zeta+1)],
                              [            -2*(eta**2-1)*(xi+1)*(zeta+1)],
                              [            -2*(eta+1)*(xi**2-1)*(zeta+1)],
                              [             2*(eta**2-1)*(xi-1)*(zeta+1)],
                              [            -2*(eta-1)*(xi-1)*(zeta**2-1)],
                              [             2*(eta-1)*(xi+1)*(zeta**2-1)],
                              [            -2*(eta+1)*(xi+1)*(zeta**2-1)],
                              [             2*(eta+1)*(xi-1)*(zeta**2-1)]])

            dN_dxi = 1/8*np.array([
                                [ (eta-1)*(zeta-1)*(eta+2*xi+zeta+1),
                                 (xi-1)*(zeta-1)*(2*eta+xi+zeta+1),
                                 (eta-1)*(xi-1)*(eta+xi+2*zeta+1)],
                                [(eta-1)*(zeta-1)*(-eta+2*xi-zeta-1),
                                 (xi+1)*(zeta-1)*(-2*eta+xi-zeta-1),
                                 (eta-1)*(xi+1)*(-eta+xi-2*zeta-1)],
                                [(eta+1)*(zeta-1)*(-eta-2*xi+zeta+1),
                                 (xi+1)*(zeta-1)*(-2*eta-xi+zeta+1),
                                 (eta+1)*(xi+1)*(-eta-xi+2*zeta+1)],
                                [ (eta+1)*(zeta-1)*(eta-2*xi-zeta-1),
                                 (xi-1)*(zeta-1)*(2*eta-xi-zeta-1),
                                 (eta+1)*(xi-1)*(eta-xi-2*zeta-1)],
                                [(eta-1)*(zeta+1)*(-eta-2*xi+zeta-1),
                                 (xi-1)*(zeta+1)*(-2*eta-xi+zeta-1),
                                 (eta-1)*(xi-1)*(-eta-xi+2*zeta-1)],
                                [ (eta-1)*(zeta+1)*(eta-2*xi-zeta+1),
                                 (xi+1)*(zeta+1)*(2*eta-xi-zeta+1),
                                 (eta-1)*(xi+1)*(eta-xi-2*zeta+1)],
                                [ (eta+1)*(zeta+1)*(eta+2*xi+zeta-1),
                                 (xi+1)*(zeta+1)*(2*eta+xi+zeta-1),
                                 (eta+1)*(xi+1)*(eta+xi+2*zeta-1)],
                                [(eta+1)*(zeta+1)*(-eta+2*xi-zeta+1),
                                 (xi-1)*(zeta+1)*(-2*eta+xi-zeta+1),
                                 (eta+1)*(xi-1)*(-eta+xi-2*zeta+1)],
                                [-4*xi*(eta-1)*(zeta-1), -2*(xi**2-1)*(zeta-1),
                                 -2*(eta-1)*(xi**2-1)],
                                [ 2*(eta**2-1)*(zeta-1), 4*eta*(xi+1)*(zeta-1),
                                 2*(eta**2-1)*(xi+1)],
                                [ 4*xi*(eta+1)*(zeta-1),  2*(xi**2-1)*(zeta-1),
                                 2*(eta+1)*(xi**2-1)],
                                [-2*(eta**2-1)*(zeta-1),-4*eta*(xi-1)*(zeta-1),
                                 -2*(eta**2-1)*(xi-1)],
                                [ 4*xi*(eta-1)*(zeta+1),  2*(xi**2-1)*(zeta+1),
                                 2*(eta-1)*(xi**2-1)],
                                [-2*(eta**2-1)*(zeta+1),-4*eta*(xi+1)*(zeta+1),
                                 -2*(eta**2-1)*(xi+1)],
                                [-4*xi*(eta+1)*(zeta+1), -2*(xi**2-1)*(zeta+1),
                                 -2*(eta+1)*(xi**2-1)],
                                [ 2*(eta**2-1)*(zeta+1), 4*eta*(xi-1)*(zeta+1),
                                 2*(eta**2-1)*(xi-1)],
                                [-2*(eta-1)*(zeta**2-1), -2*(xi-1)*(zeta**2-1),
                                 -4*zeta*(eta-1)*(xi-1)],
                                [ 2*(eta-1)*(zeta**2-1),  2*(xi+1)*(zeta**2-1),
                                 4*zeta*(eta-1)*(xi+1)],
                                [-2*(eta+1)*(zeta**2-1), -2*(xi+1)*(zeta**2-1),
                                 -4*zeta*(eta+1)*(xi+1)],
                                [ 2*(eta+1)*(zeta**2-1),  2*(xi-1)*(zeta**2-1),
                                 4*zeta*(eta+1)*(xi-1)]])

            dX_dxi = X_mat.T @ dN_dxi
            det = np.linalg.det(dX_dxi)

            M_small = N @ N.T * det * rho * w
            self.M += scatter_matrix(M_small, 3)

        return self.M


class Prism6(Element):
    '''
    Three dimensional Prism element.
    '''
    name = 'Prism6'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.K = np.zeros((18,18))
        self.f = np.zeros(18)
        self.M = np.zeros((18,18))
        self.S = np.zeros((6,6))
        self.E = np.zeros((6,6))
        return

    def _compute_tensors(self, X, u, t):
        print('Warning! the Prism6 element has no stiffness!')
        return

    def _m_int(self, X, u, t):
        print('Warning! the Prism6 element has no mass!')
        return self.M

class Bar2Dlumped(Element):
    '''
    Bar-Element with 2 nodes and lumped stiffness matrix
    '''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.K = np.zeros((4,4))
        self.M = np.zeros((4,4))
        self.f = np.zeros(4)

    def foo(self):
        self.e_modul      = self.material.E
        self.crosssec      = self.material.crossec
        self.rho           = self.material.rho


    def _compute_tensors(self, X, u, t):
        self._k_and_m_int(X, u, t)

    def _k_and_m_int(self, X, u, t):

#        X1, Y1, X2, Y2 = X
        X_mat = X.reshape(-1, 2)
        l = np.linalg.norm(X_mat[1,:]-X_mat[0,:])

        # Element stiffnes matrix
        k_el_loc = self.e_modul*self.crosssec/l*np.array([[1, -1],
                                                          [-1, 1]])
        temp = (X_mat[1,:]-X_mat[0,:])/l
        A = np.array([[temp[0], temp[1], 0,       0],
                      [0,       0,       temp[0], temp[1]]])
        k_el = A.T.dot(k_el_loc.dot(A))

        # Element mass matrix
        m_el = self.rho*self.crosssec*l/6*np.array([[3, 0, 0, 0],
                                                    [0, 3, 0, 0],
                                                    [0, 0, 3, 0],
                                                    [0, 0, 0, 3]])

        # Make symmetric (because of round-off errors)
        self.K = 1/2*(k_el+k_el.T)
        self.M = 1/2*(m_el+m_el.T)
        return self.K, self.M

    def _k_int(self, X, u, t):
        k_el, m_el = self._k_and_m_int(X, u, t)
        return k_el

    def _m_int(self, X, u, t=0):
        k_el, m_el = self._k_and_m_int(X, u, t)
        return m_el

#%%
def f_proj_a(f_mat, direction):
    '''
    Compute the force traction proportional to the area of the element
    in any-direction.

    Parameters
    ----------
    f_mat : ndarray
        normal force vector of one element in matrix notation. The shape of
        `f_mat`  is (no_of_nodes, dofs_per_node)
        It weights the participations of the nodes to the defined force
        e.g. for line element: a half for each node times length of the element
    direction : ndarray
        normalized vector describing the direction, in which the force should
        act.

    Returns
    -------
    f : ndarray
        force vector of traction vector in voigt notation (1d-array)

    '''
    n_nodes, dofs_per_node = f_mat.shape
    f_out = np.zeros(n_nodes * dofs_per_node)
    for i, f_vec in enumerate(f_mat):
        f_out[i*dofs_per_node:(i+1)*dofs_per_node] = direction * np.sqrt(f_vec @ f_vec)
    return f_out

def f_proj_a_shadow(f_mat, direction):
    '''
    Compute the force projection in any direction proportional to the projected
    area, i.e. the shadow-area, the area throws in the given direction.

    Parameters
    ----------
    f_mat : ndarray
        normal force vector of one element in matrix notation. The shape of
        `f_mat`  is (no_of_nodes, dofs_per_node)
    direction : ndarray
        normalized vector describing the direction, in which the force should
        act.

    Returns
    -------
    f : ndarray
        force vector of traction vector in voigt notation (1d-array)

    '''
    n_nodes, dofs_per_node = f_mat.shape
    f_out = np.zeros(n_nodes * dofs_per_node)
    for i, f_vec in enumerate(f_mat):
        # by Johannes Rutzmoser:
        # f_out[i*dofs_per_node:(i+1)*dofs_per_node] = direction * (direction @ f_vec)
        # by Christian Meyer: I think this has to be divided by || direction || because of projection
        f_out[i * dofs_per_node:(i + 1) * dofs_per_node] = direction * ((direction @ f_vec) / np.linalg.norm(direction))

    return f_out



class BoundaryElement(Element):
    '''
    Class for the application of Neumann Boundary Conditions.

    Attributes
    ----------
    time_func : func
        function returning a value between {-1, 1} which is time dependent
        storing the time dependency of the Neumann Boundary condition.
        Example for constant function:

        >>> def func(t):
        >>>    return 1

    f_proj : func
        function producing the nodal force vector from the given nodal force
        vector in normal direction.

    val : float
    
    direct : {'normal', numpy.array}
        'normal' means that force acts normal to the current surface
        numpy.array is a vector in which the force should act (with global coordinate system as reference)
    
    f : numpy.array
        local external force vector of the element
    
    K : numpy.array
        tangent stiffness matrix of the element (for boundary elements typically zero)
    
    M : numpy.array
        mass matrix of the element (for boundary elements typically zero)
    
        '''

    def __init__(self, val, ndof, direct='normal', time_func=None,
                 shadow_area=False):
        '''
        Parameters
        ----------
        val : float
            scale value for the pressure/traction onto the element
        ndof : int
            number of dofs of the boundary element
        direct : str 'normal' or ndarray, optional
            array giving the direction, in which the traction force should act.
            alternatively, the keyword 'normal' may be given.
            Normal means that the force will follow the normal of the surface
            Default value: 'normal'.
        time_func : function object
            Function object returning a value between -1 and 1 given the
            input t:

            >>> f_applied = val * time_func(t)

        shadow_area : bool, optional
            Flat setting, if force should be proportional to the shadow area,
            i.e. the area of the surface projected on the direction. Default
            value: 'False'.

        Returns
        -------
        None
        '''
        self.val = val
        self.f = np.zeros(ndof)
        self.K = np.zeros((ndof, ndof))
        self.M = np.zeros((ndof, ndof))
        self.direct = direct

        # select the correct f_proj function in order to fulfill the direct
        # and shadow area specification
        if direct is 'normal':
            def f_proj(f_mat):
                return f_mat.flatten()
        else: # direct has to be a vector
            # save direct to be an array
            self.direct = np.array(direct)
            if shadow_area: # projected solution
                def f_proj(f_mat):
                    return f_proj_a_shadow(f_mat, self.direct)
            else: # non-projected solution
                def f_proj(f_mat):
                    return f_proj_a(f_mat, self.direct)

        self.f_proj = f_proj
        # time function...
        def const_func(t):
            return 1
        if time_func is None:
            self.time_func = const_func
        else:
            self.time_func = time_func

    def _m_int(self, X, u, t=0):
        return self.M




class Tri3Boundary(BoundaryElement):
    '''
    Class for application of Neumann Boundary Conditions.
    '''

    def __init__(self, val, direct, time_func=None, shadow_area=False):
        super().__init__(val=val, direct=direct, time_func=time_func,
                         shadow_area=shadow_area, ndof=9)

    def _compute_tensors(self, X, u, t):
        x_vec = (X+u).reshape((-1, 3)).T
        v1 = x_vec[:,2] - x_vec[:,0]
        v2 = x_vec[:,1] - x_vec[:,0]
        n = np.cross(v1, v2)/2
        N = np.array([1/3, 1/3, 1/3])
        f_mat = np.outer(N, n)
        # positive sign as it is external force on the right hand side of the
        # function
        self.f = self.f_proj(f_mat) * self.val * self.time_func(t)

class Tri6Boundary(BoundaryElement):
    '''
    Boundary element with variatonally consistent boundary forces.

    Notes
    -----
    This function has been updated to give a variationally consistent
    integrated skin element.
    '''

    # Gauss-Points like ABAQUS or ANSYS
    gauss_points = ((1/6, 1/6, 2/3, 1/3),
                    (1/6, 2/3, 1/6, 1/3),
                    (2/3, 1/6, 1/6, 1/3))


    def __init__(self, val, direct, time_func=None, shadow_area=False):
        super().__init__(val=val, direct=direct, time_func=time_func,
                         shadow_area=shadow_area, ndof=18)

    def _compute_tensors(self, X, u, t):
        '''
        Compute the full pressure contribution by performing gauss integration.

        '''
        # self.f *= 0
        f_mat = np.zeros((6,3))
        x_vec = (X+u).reshape((-1, 3))

        # gauss point evaluation of full pressure field
        for L1, L2, L3, w in self.gauss_points:
            N = np.array([L1*(2*L1 - 1), L2*(2*L2 - 1), L3*(2*L3 - 1),
                          4*L1*L2, 4*L2*L3, 4*L1*L3])

            dN_dL = np.array([  [4*L1 - 1,        0,        0],
                                [       0, 4*L2 - 1,        0],
                                [       0,        0, 4*L3 - 1],
                                [    4*L2,     4*L1,        0],
                                [       0,     4*L3,     4*L2],
                                [    4*L3,        0,     4*L1]])

            dx_dL = x_vec.T @ dN_dL
            v1 = dx_dL[:,2] - dx_dL[:,0]
            v2 = dx_dL[:,1] - dx_dL[:,0]
            n = np.cross(v1, v2)
            f_mat += np.outer(N, n) / 2 * w
        # no minus sign as force will be on the right hand side of eqn.
        self.f = self.f_proj(f_mat) * self.val * self.time_func(t)

class Quad4Boundary(BoundaryElement):
    '''
    Quad4 boundary element for 3D-Problems.
    '''
    g1 = 1/np.sqrt(3)

    gauss_points = ((-g1, -g1, 1.),
                    ( g1, -g1, 1.),
                    ( g1,  g1, 1.),
                    (-g1,  g1, 1.))

    def __init__(self, val, direct, time_func=None, shadow_area=False):
        super().__init__(val=val, direct=direct, time_func=time_func,
                         shadow_area=shadow_area, ndof=12)
        return

    def _compute_tensors(self, X, u, t):
        '''
        Compute the full pressure contribution by performing gauss integration.

        '''
        f_mat = np.zeros((4,3))
        x_vec = (X+u).reshape((4, 3))

        # gauss point evaluation of full pressure field
        for xi, eta, w in self.gauss_points:

            N = np.array([  [(-eta + 1)*(-xi + 1)/4],
                            [ (-eta + 1)*(xi + 1)/4],
                            [  (eta + 1)*(xi + 1)/4],
                            [ (eta + 1)*(-xi + 1)/4]])

            dN_dxi = np.array([ [ eta/4 - 1/4,  xi/4 - 1/4],
                                [-eta/4 + 1/4, -xi/4 - 1/4],
                                [ eta/4 + 1/4,  xi/4 + 1/4],
                                [-eta/4 - 1/4, -xi/4 + 1/4]])

            dx_dxi = x_vec.T @ dN_dxi
            n = np.cross(dx_dxi[:,1], dx_dxi[:,0])
            f_mat += np.outer(N, n) * w
        # no minus sign as force will be on the right hand side of eqn.
        self.f = self.f_proj(f_mat) * self.val * self.time_func(t)

class Quad8Boundary(BoundaryElement):
    '''
    Quad8 boundary element for 3D-Problems.
    '''
    g = np.sqrt(3/5)
    w = 5/9
    w0 = 8/9
    gauss_points = ((-g, -g,  w*w), ( g, -g,  w*w ), ( g,  g,   w*w),
                    (-g,  g,  w*w), ( 0, -g, w0*w ), ( g,  0,  w*w0),
                    ( 0,  g, w0*w), (-g,  0,  w*w0), ( 0,  0, w0*w0))

    def __init__(self, val, direct, time_func=None, shadow_area=False):
        super().__init__(val=val, direct=direct, time_func=time_func,
                         shadow_area=shadow_area, ndof=24)
        return

    def _compute_tensors(self, X, u, t):
        '''
        Compute the full pressure contribution by performing gauss integration.

        '''
        f_mat = np.zeros((8,3))
        x_vec = (X+u).reshape((8, 3))

        # gauss point evaluation of full pressure field
        for xi, eta, w in self.gauss_points:

            N = np.array([  [(-eta + 1)*(-xi + 1)*(-eta - xi - 1)/4],
                            [ (-eta + 1)*(xi + 1)*(-eta + xi - 1)/4],
                            [   (eta + 1)*(xi + 1)*(eta + xi - 1)/4],
                            [  (eta + 1)*(-xi + 1)*(eta - xi - 1)/4],
                            [             (-eta + 1)*(-xi**2 + 1)/2],
                            [              (-eta**2 + 1)*(xi + 1)/2],
                            [              (eta + 1)*(-xi**2 + 1)/2],
                            [             (-eta**2 + 1)*(-xi + 1)/2]])

            dN_dxi = np.array([
                [-(eta - 1)*(eta + 2*xi)/4, -(2*eta + xi)*(xi - 1)/4],
                [ (eta - 1)*(eta - 2*xi)/4,  (2*eta - xi)*(xi + 1)/4],
                [ (eta + 1)*(eta + 2*xi)/4,  (2*eta + xi)*(xi + 1)/4],
                [-(eta + 1)*(eta - 2*xi)/4, -(2*eta - xi)*(xi - 1)/4],
                [             xi*(eta - 1),            xi**2/2 - 1/2],
                [          -eta**2/2 + 1/2,            -eta*(xi + 1)],
                [            -xi*(eta + 1),           -xi**2/2 + 1/2],
                [           eta**2/2 - 1/2,             eta*(xi - 1)]])

            dx_dxi = x_vec.T @ dN_dxi
            n = np.cross(dx_dxi[:,1], dx_dxi[:,0])
            f_mat += np.outer(N, n) * w
        # no minus sign as force will be on the right hand side of eqn.
        self.f = self.f_proj(f_mat) * self.val * self.time_func(t)


class LineLinearBoundary(BoundaryElement):
    '''
    Line Boundary element for 2D-Problems.
    '''
    # Johannes Rutzmoser: rot_mat is a rotationmatrix, that turns +90deg
    # rot_mat = np.array([[0,-1], [1, 0]])
    # Christian Meyer: more intuitiv: boundary in math. positive direction equals outer vector => rotate -90deg:
    rot_mat = np.array([[0, 1], [-1, 0]])
    # weighting for the two nodes
    N = np.array([1/2, 1/2])

    def __init__(self, val, direct, time_func=None, shadow_area=False, ):
        super().__init__(val=val, direct=direct, time_func=time_func,
                         shadow_area=shadow_area, ndof=4)

    def _compute_tensors(self, X, u, t):
        x_vec = (X+u).reshape((-1, 2)).T
        # Connection line between two nodes of the element
        v = x_vec[:,1] - x_vec[:,0]
        # Generate the orthogonal vector to connection line by rotation 90deg
        n = self.rot_mat @ v
        # Remember: n must not be normalized because forces are defined as force-values per area of forces per line
        # Thus the given forces have to be scaled with the area or line length respectively.
        #
        # f_mat: Generate the weights or in other words participations of each dof to generate force
        # Dimension of f_mat: (number of nodes, number of dofs per node)
        f_mat = np.outer(self.N, n)
        self.f = self.f_proj(f_mat) * self.val * self.time_func(t)


class LineQuadraticBoundary(BoundaryElement):
    '''
    Quadratic line boundary element for 2D problems.
    '''

    #rot_mat = np.array([[ 0, -1],
    #                    [ 1,  0]])
    # same as above:
    rot_mat = np.array([[0, 1],[-1, 0]])

    N = np.array([1, 1, 4])/6

    def __init__(self, val, direct, time_func=None, shadow_area=False):

        super().__init__(val=val, direct=direct, time_func=time_func,
                         shadow_area=shadow_area, ndof=6)

    def _compute_tensors(self, X, u, t):
        x_vec = (X+u).reshape((-1, 2)).T
        v = x_vec[:,1] - x_vec[:,0]
        n = self.rot_mat @ v
        f_mat = np.outer(self.N, n)
        self.f = self.f_proj(f_mat) * self.val * self.time_func(t)


#%%
if use_fortran:
    def compute_tri3_tensors(self, X, u, t):
        '''Wrapping funktion for fortran function call.'''
        self.K, self.f, self.S, self.E = amfe.f90_element.tri3_k_f_s_e(\
            X, u, self.material.thickness, self.material.S_Sv_and_C_2d)

    def compute_tri6_tensors(self, X, u, t):
        '''Wrapping funktion for fortran function call.'''
        self.K, self.f, self.S, self.E = amfe.f90_element.tri6_k_f_s_e(\
            X, u, self.material.thickness, self.material.S_Sv_and_C_2d)

    def compute_tri6_mass(self, X, u, t=0):
        '''Wrapping funktion for fortran function call.'''
        self.M = amfe.f90_element.tri6_m(\
            X, self.material.rho, self.material.thickness)
        return self.M

    def compute_tet4_tensors(self, X, u, t):
        '''Wrapping funktion for fortran function call.'''
        self.K, self.f, self.S, self.E = amfe.f90_element.tet4_k_f_s_e( \
            X, u, self.material.S_Sv_and_C)

    def compute_tet10_tensors(self, X, u, t):
        '''Wrapping funktion for fortran function call.'''
        self.K, self.f, self.S, self.E = amfe.f90_element.tet10_k_f_s_e( \
            X, u, self.material.S_Sv_and_C)

    def compute_hexa8_tensors(self, X, u, t):
        '''Wrapping funktion for fortran function call.'''
        self.K, self.f, self.S, self.E = amfe.f90_element.hexa8_k_f_s_e( \
            X, u, self.material.S_Sv_and_C)

    def compute_hexa20_tensors(self, X, u, t):
        '''Wrapping funktion for fortran function call.'''
        self.K, self.f, self.S, self.E = amfe.f90_element.hexa20_k_f_s_e( \
            X, u, self.material.S_Sv_and_C)

    def compute_hexa20_mass(self, X, u, t=0):
        '''Wrapping funktion for fortran function call.'''
        self.M = amfe.f90_element.hexa20_m(X, self.material.rho)
        return self.M

    # overloading the routines with fortran routines
    Tri3._compute_tensors_python = Tri3._compute_tensors
    Tri6._compute_tensors_python = Tri6._compute_tensors
    Tri6._m_int_python = Tri6._m_int
    Tet4._compute_tensors_python = Tet4._compute_tensors
    Tet10._compute_tensors_python = Tet10._compute_tensors
    Hexa8._compute_tensors_python = Hexa8._compute_tensors
    Hexa20._compute_tensors_python = Hexa20._compute_tensors
    Hexa20._m_int_python = Hexa20._m_int


    Tri3._compute_tensors = compute_tri3_tensors
    Tri6._compute_tensors = compute_tri6_tensors
    Tri6._m_int = compute_tri6_mass
    Tet4._compute_tensors = compute_tet4_tensors
    Tet10._compute_tensors = compute_tet10_tensors
    Hexa8._compute_tensors = compute_hexa8_tensors
    Hexa20._compute_tensors = compute_hexa20_tensors
    Hexa20._m_int = compute_hexa20_mass
