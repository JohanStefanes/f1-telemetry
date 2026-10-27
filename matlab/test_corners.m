% TEST_CORNERS  Same synthetic lap as test_corners_are_the_slow_points_of_a_lap in tests/test_pipeline.py.
% 300 km/h straight with two corners: 90 km/h at 1000 m and 150 km/h at 2200 m.
x = 0:10:2990;
v = 300 - max(0, 210 - abs(x - 1000) * 0.7) - max(0, 150 - abs(x - 2200) * 0.5);
[d, m] = corners(x, v);
assert(isequal(round(d'), [1000 2200]));
assert(isequal(round(m'), [90 150]));
disp('test_corners: ok');
