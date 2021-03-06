cl__1 = 1;
Point(1) = {0, 0, 0, 1};
Point(2) = {0.5, 0, 0, 1};
Point(3) = {0.5, 0.5, 0, 1};
Point(4) = {0.5, -0.5, 0, 1};
Point(5) = {1, -0, 0, 1};
Point(6) = {0.5, 0.8, 0, 1};
Point(7) = {-0.3, 0, 0, 1};
Point(8) = {0.5, -0.8, 0, 1};
Point(9) = {1.3, 0, 0, 1};
Point(10) = {0.5, 0.3, 0, 1};
Point(11) = {0.2, -0, 0, 1};
Point(12) = {0.8, -0, 0, 1};
Point(13) = {0.5, -0.3, 0, 1};
Point(15) = {6.4, -0, 0, 1};
Point(16) = {6.4, 0.7, 0, 1};
Point(18) = {6.4, -0.7, 0, 1};
Point(20) = {7.1, -0, -0, 1};
Point(21) = {5.7, -0, -0, 1};
Point(22) = {6.4, 0.9, -0, 1};
Point(23) = {7.3, -0, -0, 1};
Point(24) = {6.4, -0.9, -0, 1};
Point(25) = {5.5, -0, -0, 1};
Point(26) = {6.4, 1.3, 0, 1};
Point(27) = {7.7, -0, -0, 1};
Point(28) = {6.4, -1.3, -0, 1};
Point(29) = {1.8, 0.4, 0, 1};
Point(30) = {1.8, -0.3, -0, 1};
Point(31) = {4.7, 0.5, 0, 1};
Point(32) = {4.7, -0.4, -0, 1};
Circle(1) = {10, 2, 12};
Circle(2) = {12, 2, 13};
Circle(3) = {13, 2, 11};
Circle(4) = {11, 2, 10};
Circle(5) = {3, 2, 5};
Circle(6) = {5, 2, 4};
Circle(7) = {4, 2, 1};
Circle(8) = {1, 2, 3};
Circle(9) = {16, 15, 20};
Circle(10) = {20, 15, 18};
Circle(11) = {18, 15, 21};
Circle(12) = {21, 15, 16};
Circle(13) = {22, 15, 23};
Circle(14) = {23, 15, 24};
Circle(15) = {24, 15, 25};
Circle(16) = {25, 15, 22};
Spline(17) = {29, 6, 7, 8, 30, 32, 28, 27
, 26, 31, 29};
Line Loop(23) = {5, 6, 7, 8, -4, -3, -2, -1};
Plane Surface(23) = {23};
Line Loop(25) = {16, 13, 14, 15, -11, -10, -9, -12};
Plane Surface(25) = {25};
Line Loop(26) = {5, 6, 7, 8};
Line Loop(27) = {17};
Line Loop(28) = {16, 13, 14, 15};
Plane Surface(29) = {26, 27, 28};
Delete {
  Line{17};
}
Delete {
  Line{17};
}
Delete {
  Line{17};
}
Delete {
  Surface{29};
}
Delete {
  Line{17};
}
Circle(29) = {6, 2, 7};
Circle(30) = {7, 2, 8};
Circle(31) = {26, 15, 27};
Circle(32) = {27, 15, 28};
Spline(33) = {6, 29, 31, 26};
Spline(34) = {8, 30, 32, 28};
Line Loop(35) = {33, 31, 32, -34, -30, -29};
Plane Surface(36) = {26, 28, 35};
Extrude {0, 0, 0.4} {
  Surface{23, 25};
}
Extrude {0, 0, 0.4} {
  Surface{36};
}
Extrude {0, 0, 0.1} {
  Surface{78, 120};
}
Extrude {0, 0, -0.1} {
  Surface{25, 23};
}
Physical Volume(361) = {3, 2, 5, 6, 4, 1, 7};
Physical Surface(362) = {111, 267, 309, 107, 305, 263, 275, 119, 317, 115, 313, 271};
Physical Surface(363) = {69, 351, 225, 73, 229, 355, 65, 221, 347, 77, 233, 359};
