cl__1 = 1;
Point(1) = {0, 0, 0, 1};
Point(2) = {2, 0, 0, 1};
Point(3) = {2, 0.5, 0, 1};
Point(4) = {0, 0.5, 0, 1};
Point(5) = {0, 0, 0.5, 1};
Point(6) = {2, 0, 0.5, 1};
Point(7) = {2, 0.5, 0.5, 1};
Point(8) = {0, 0.5, 0.5, 1};
Line(1) = {1, 2};
Line(2) = {2, 3};
Line(3) = {3, 4};
Line(4) = {4, 1};
Line(8) = {7, 8};
Line(9) = {8, 5};
Line(10) = {5, 6};
Line(11) = {6, 7};
Line(13) = {3, 7};
Line(14) = {4, 8};
Line(18) = {1, 5};
Line(22) = {2, 6};
Line Loop(6) = {3, 4, 1, 2};
Plane Surface(6) = {6};
Line Loop(15) = {3, 14, -8, -13};
Ruled Surface(15) = {15};
Line Loop(19) = {4, 18, -9, -14};
Ruled Surface(19) = {19};
Line Loop(23) = {1, 22, -10, -18};
Ruled Surface(23) = {23};
Line Loop(27) = {2, 13, -11, -22};
Ruled Surface(27) = {27};
Line Loop(28) = {8, 9, 10, 11};
Plane Surface(28) = {28};
Surface Loop(1) = {6, 15, 19, 23, 27, 28};
Volume(1) = {1};
Physical Volume(29) = {1};
Physical Surface(30) = {27};
Physical Surface(31) = {19};
