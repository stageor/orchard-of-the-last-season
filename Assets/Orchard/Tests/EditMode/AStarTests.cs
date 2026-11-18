using System;
using System.Collections.Generic;
using NUnit.Framework;
using Orchard;

namespace Orchard.Tests
{
    // Exercises the production AStar implementation in Assets/Orchard/Scripts/AStar.cs against
    // an independent Dijkstra oracle. The oracle uses the documented movement contract:
    // 8 directions, diagonal cost sqrt(2), mud cost x3, hills/bushes/logs block, no corner cuts.
    [TestFixture]
    public class AStarTests
    {
        TestWorld world;

        [SetUp]
        public void SetUp()
        {
            world = new TestWorld(4711);
            world.Fill(C.GRASS);
        }

        [TearDown]
        public void TearDown()
        {
            world.Dispose();
        }

        [Test]
        public void FindPath_OnOpenGround_ReturnsStraightShortestRoute()
        {
            List<Cell> path = AStar.FindPath(new Cell(1, 1), new Cell(5, 1));

            Assert.NotNull(path);
            Assert.AreEqual(5, path.Count, "one cell per step including start and goal");
            Assert.AreEqual(new Cell(1, 1), path[0]);
            Assert.AreEqual(new Cell(5, 1), path[path.Count - 1]);
            for (int i = 0; i < path.Count; i++) Assert.AreEqual(1, path[i].cy, "route must stay on the open row");
            Assert.AreEqual(4.0, PathCost(path), 1e-9);
            Assert.AreEqual(ReferenceCost(new Cell(1, 1), new Cell(5, 1)), PathCost(path), 1e-9);
        }

        [Test]
        public void FindPath_StartEqualsGoal_ReturnsSingleCell()
        {
            List<Cell> path = AStar.FindPath(new Cell(4, 4), new Cell(4, 4));

            Assert.NotNull(path);
            Assert.AreEqual(1, path.Count);
            Assert.AreEqual(new Cell(4, 4), path[0]);
            Assert.AreEqual(0.0, PathCost(path), 1e-9);
        }

        [Test]
        public void FindPath_AlreadyInGoalCell_IsAccepted()
        {
            // A goal cell may hold a tree; standing on it is still a valid (zero length) path.
            world.AddTree(6, 6);
            List<Cell> path = AStar.FindPath(new Cell(6, 6), new Cell(6, 6));

            Assert.NotNull(path);
            Assert.AreEqual(1, path.Count);
        }

        [Test]
        public void FindPath_BlockedByWall_ReturnsNull()
        {
            world.Wall(3, 0, C.GH - 1);

            List<Cell> path = AStar.FindPath(new Cell(1, 5), new Cell(5, 5));

            Assert.IsNull(path, "a wall of hills across the whole board must make the goal unreachable");
            Assert.AreEqual(double.PositiveInfinity, ReferenceCost(new Cell(1, 5), new Cell(5, 5)));
        }

        [Test]
        public void FindPath_UnreachableGoal_ReturnsNull()
        {
            // Seal the goal in a 3x3 box of hills.
            for (int dx = -1; dx <= 1; dx++)
                for (int dy = -1; dy <= 1; dy++)
                    if (dx != 0 || dy != 0) world.Set(10 + dx, 5 + dy, C.HILL);

            Assert.IsNull(AStar.FindPath(new Cell(1, 1), new Cell(10, 5)));
        }

        [Test]
        public void FindPath_GoalOutsideBoard_ReturnsNull()
        {
            Assert.IsNull(AStar.FindPath(new Cell(1, 1), new Cell(C.GW + 2, 3)));
            Assert.IsNull(AStar.FindPath(new Cell(1, 1), new Cell(-1, 3)));
        }

        [Test]
        public void FindPath_StartOutsideBoard_ReturnsNull()
        {
            Assert.IsNull(AStar.FindPath(new Cell(-1, 3), new Cell(1, 1)));
        }

        [Test]
        public void FindPath_AvoidsMud_WhenDetourIsCheaper()
        {
            world.Set(5, 5, C.MUD);
            world.Set(6, 5, C.MUD);

            List<Cell> path = AStar.FindPath(new Cell(1, 5), new Cell(9, 5));

            Assert.NotNull(path);
            foreach (Cell c in path)
                Assert.AreNotEqual(C.MUD, world.game.grid[c.cx, c.cy], "A* should walk around a costly mud band");

            double cost = PathCost(path);
            Assert.Less(cost, 13.0, "walking straight through two mud cells costs 13");
            Assert.AreEqual(ReferenceCost(new Cell(1, 5), new Cell(9, 5)), cost, 1e-9, "path must be cost optimal");
        }

        [Test]
        public void FindPath_WalksThroughMud_WhenItIsStillCheaper()
        {
            // A full column of mud makes the detour to either edge longer than one muddy step.
            world.Wall(5, 0, C.GH - 1, C.MUD);

            List<Cell> path = AStar.FindPath(new Cell(1, 5), new Cell(9, 5));

            Assert.NotNull(path);
            Assert.AreEqual(ReferenceCost(new Cell(1, 5), new Cell(9, 5)), PathCost(path), 1e-9);
            bool steppedOnMud = false;
            foreach (Cell c in path) if (world.game.grid[c.cx, c.cy] == C.MUD) steppedOnMud = true;
            Assert.IsTrue(steppedOnMud, "a single mud cell is cheaper than a detour");
        }

        [Test]
        public void FindPath_DoesNotCutDiagonalCorners()
        {
            world.Set(3, 2, C.HILL);
            world.Set(2, 3, C.HILL);

            List<Cell> path = AStar.FindPath(new Cell(2, 2), new Cell(4, 4));

            Assert.NotNull(path);
            Assert.Greater(path.Count, 3, "the illegal diagonal would only need 3 cells");
            Assert.AreNotEqual(new Cell(3, 3), path[1], "must not squeeze between two blocked cells");
            AssertNoCornerCut(path);
            Assert.AreEqual(ReferenceCost(new Cell(2, 2), new Cell(4, 4)), PathCost(path), 1e-9);
        }

        [Test]
        public void FindPathToAny_ChoosesCheapestGoal_NotNearestAsTheCrowFlies()
        {
            world.Set(4, 2, C.MUD);
            world.Set(5, 2, C.MUD);
            List<Cell> goals = new List<Cell> { new Cell(5, 2), new Cell(2, 6) };

            List<Cell> path = AStar.FindPathToAny(new Cell(2, 2), goals);

            Assert.NotNull(path);
            Assert.AreEqual(new Cell(2, 6), path[path.Count - 1],
                "goal (5,2) is closer in a straight line but costs more because of mud");
            Assert.AreEqual(CheapestReferenceCost(new Cell(2, 2), goals), PathCost(path), 1e-9);
        }

        [Test]
        public void FindPathToAny_WithNoGoals_ReturnsNull()
        {
            Assert.IsNull(AStar.FindPathToAny(new Cell(1, 1), new List<Cell>()));
        }

        [Test]
        public void FindPathToAny_IgnoresGoalsOutsideTheBoard()
        {
            List<Cell> goals = new List<Cell> { new Cell(99, 99), new Cell(3, 3) };

            List<Cell> path = AStar.FindPathToAny(new Cell(1, 1), goals);

            Assert.NotNull(path);
            Assert.AreEqual(new Cell(3, 3), path[path.Count - 1]);
        }

        [Test]
        public void FindPath_GoesAroundBushesAndLogs()
        {
            world.Set(3, 5, C.BUSH);
            world.Set(4, 5, C.LOG);

            List<Cell> path = AStar.FindPath(new Cell(1, 5), new Cell(6, 5));

            Assert.NotNull(path);
            foreach (Cell c in path)
            {
                Assert.AreNotEqual(C.BUSH, world.game.grid[c.cx, c.cy]);
                Assert.AreNotEqual(C.LOG, world.game.grid[c.cx, c.cy]);
            }
            Assert.AreEqual(ReferenceCost(new Cell(1, 5), new Cell(6, 5)), PathCost(path), 1e-9);
        }

        [Test]
        public void Smooth_OpenStraightPath_ReducesToFinalWaypoint()
        {
            List<Cell> path = AStar.FindPath(new Cell(1, 5), new Cell(9, 5));

            List<Pos> pts = AStar.Smooth(U.cc(1, 5), path, 8);

            Assert.AreEqual(1, pts.Count, "a straight run needs one waypoint");
            Assert.AreEqual(U.cc(9, 5).x, pts[0].x, 1e-9);
            Assert.AreEqual(U.cc(9, 5).y, pts[0].y, 1e-9);
        }

        [Test]
        public void Smooth_EmptyOrNullPath_ReturnsEmptyList()
        {
            Assert.AreEqual(0, AStar.Smooth(new Pos(0, 0), null, 8).Count);
            Assert.AreEqual(0, AStar.Smooth(new Pos(0, 0), new List<Cell>(), 8).Count);
        }

        [Test]
        public void Smooth_SingleCellPath_ReturnsThatCell()
        {
            List<Cell> path = new List<Cell> { new Cell(4, 4) };

            List<Pos> pts = AStar.Smooth(new Pos(0, 0), path, 8);

            Assert.AreEqual(1, pts.Count);
            Assert.AreEqual(U.cc(4, 4).x, pts[0].x, 1e-9);
            Assert.AreEqual(U.cc(4, 4).y, pts[0].y, 1e-9);
        }

        [Test]
        public void Smooth_DoesNotCutThroughWalls()
        {
            // Leave the two top rows open: a wall that spans the whole board would make the
            // goal unreachable, and the test would never exercise smoothing at all.
            world.Wall(6, 0, C.GH - 3);
            List<Cell> path = AStar.FindPath(new Cell(1, 5), new Cell(11, 5));
            Assert.NotNull(path);

            List<Pos> pts = AStar.Smooth(U.cc(1, 5), path, 9);

            Assert.Greater(pts.Count, 0);
            Pos prev = U.cc(1, 5);
            foreach (Pos p in pts)
            {
                AssertWalkableSegment(prev, p);
                prev = p;
            }
            Assert.AreEqual(U.cc(11, 5).x, pts[pts.Count - 1].x, 1e-9);
        }

        [Test]
        public void Perception_LineOfSight_IsBlockedByHillsOnly()
        {
            Pos a = U.cc(1, 2), b = U.cc(9, 2);
            Assert.IsTrue(Perception.LineOfSight(a, b), "open grass must be visible");

            world.Set(5, 2, C.HILL);
            Assert.IsFalse(Perception.LineOfSight(a, b), "a hill blocks sight");

            world.Set(5, 2, C.BUSH);
            Assert.IsTrue(Perception.LineOfSight(a, b), "a bush does not block sight");
        }

        [Test]
        public void Perception_WalkableLine_RejectsBushesLogsAndHills_ButNotMud()
        {
            Pos a = U.cc(1, 2), b = U.cc(9, 2);
            Assert.IsTrue(Perception.WalkableLine(a, b));

            world.Set(5, 2, C.MUD);
            Assert.IsTrue(Perception.WalkableLine(a, b), "mud is walkable");

            world.Set(5, 2, C.BUSH);
            Assert.IsFalse(Perception.WalkableLine(a, b));

            world.Set(5, 2, C.LOG);
            Assert.IsFalse(Perception.WalkableLine(a, b));

            world.Set(5, 2, C.HILL);
            Assert.IsFalse(Perception.WalkableLine(a, b));
        }

        [Test]
        public void Steering_Slot_StandsOnTheWalkersSideOfTheTree()
        {
            Pos tree = U.cc(5, 5);
            Shambler e = world.AddShambler(tree.x + 100, tree.y);

            Pos slot = Steering.slot(e, tree, 20);

            Assert.AreEqual(20.0, U.dist(slot, tree), 1e-6);
            Assert.Greater(slot.x, tree.x, "the slot must stay on the attacker's side");
        }

        [Test]
        public void Steering_Separate_PushesOverlappingGroundWalkersApart()
        {
            Shambler a = world.AddShambler(200, 200);
            world.AddShambler(205, 200);
            double before = U.dist(a, world.game.enemies[1]);

            Steering.separate(a, 0.1);

            Assert.Greater(U.dist(a, world.game.enemies[1]), before, "overlapping walkers must separate");
            Assert.Less(a.x, 200, "the left walker is pushed left");
        }

        [Test]
        public void Steering_MoveGround_StopsAtHills()
        {
            world.Set(5, 5, C.HILL);
            Mover e = new Mover();
            e.r = 10;
            e.x = 4 * C.CELL + 40;      // last pixels of the cell left of the hill column
            e.y = 5 * C.CELL + 22;

            Steering.moveGround(e, 10, 0);

            Assert.AreEqual(4 * C.CELL + 40, e.x, 1e-9, "the walker must not enter the hill cell");
        }

        // ---------------- independent oracle ----------------

        static void AssertNoCornerCut(List<Cell> path)
        {
            for (int i = 1; i < path.Count; i++)
            {
                int dx = path[i].cx - path[i - 1].cx;
                int dy = path[i].cy - path[i - 1].cy;
                if (Math.Abs(dx) != 1 || Math.Abs(dy) != 1) continue;
                Assert.IsFalse(U.groundBlocked(path[i - 1].cx + dx, path[i - 1].cy),
                    "diagonal step cut past a blocked orthogonal cell");
                Assert.IsFalse(U.groundBlocked(path[i - 1].cx, path[i - 1].cy + dy),
                    "diagonal step cut past a blocked orthogonal cell");
            }
        }

        static void AssertWalkableSegment(Pos a, Pos b)
        {
            double len = U.dist(a, b);
            int steps = Math.Max(1, (int)Math.Ceiling(len / 4));
            for (int i = 0; i <= steps; i++)
            {
                double t = (double)i / steps;
                Cell c = U.w2c(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t);
                Assert.IsFalse(U.groundBlocked(c.cx, c.cy), "smoothed segment crossed a blocked cell at " + c.cx + "," + c.cy);
            }
        }

        static double StepCost(Cell from, Cell to)
        {
            int t = OrchardGame.I.grid[to.cx, to.cy];
            double terrain = t == C.MUD ? 3.0 : 1.0;
            bool diag = from.cx != to.cx && from.cy != to.cy;
            return (diag ? Math.Sqrt(2) : 1.0) * terrain;
        }

        static double PathCost(List<Cell> path)
        {
            if (path == null) return double.PositiveInfinity;
            double cost = 0;
            for (int i = 1; i < path.Count; i++) cost += StepCost(path[i - 1], path[i]);
            return cost;
        }

        static double CheapestReferenceCost(Cell start, List<Cell> goals)
        {
            double best = double.PositiveInfinity;
            foreach (Cell g in goals) best = Math.Min(best, ReferenceCost(start, g));
            return best;
        }

        // Plain Dijkstra, written independently of AStar.cs so both the distance and the
        // route choice are checked against a different implementation.
        static double ReferenceCost(Cell start, Cell goal)
        {
            if (!U.inB(start.cx, start.cy) || !U.inB(goal.cx, goal.cy)) return double.PositiveInfinity;
            double[,] dist = new double[C.GW, C.GH];
            for (int x = 0; x < C.GW; x++)
                for (int y = 0; y < C.GH; y++) dist[x, y] = double.PositiveInfinity;
            bool[,] done = new bool[C.GW, C.GH];
            dist[start.cx, start.cy] = 0;
            int[] dx = { 1, -1, 0, 0, 1, 1, -1, -1 };
            int[] dy = { 0, 0, 1, -1, 1, -1, 1, -1 };

            while (true)
            {
                int bx = -1, by = -1;
                double bd = double.PositiveInfinity;
                for (int x = 0; x < C.GW; x++)
                    for (int y = 0; y < C.GH; y++)
                        if (!done[x, y] && dist[x, y] < bd) { bd = dist[x, y]; bx = x; by = y; }
                if (bx < 0) break;
                if (bx == goal.cx && by == goal.cy) return bd;
                done[bx, by] = true;
                for (int k = 0; k < 8; k++)
                {
                    int nx = bx + dx[k], ny = by + dy[k];
                    if (!U.inB(nx, ny)) continue;
                    bool goalCell = nx == goal.cx && ny == goal.cy;
                    if (U.groundBlocked(nx, ny) && !goalCell) continue;
                    if (k >= 4 && (U.groundBlocked(bx + dx[k], by) || U.groundBlocked(bx, by + dy[k]))) continue;
                    double nd = bd + StepCost(new Cell(bx, by), new Cell(nx, ny));
                    if (nd < dist[nx, ny]) dist[nx, ny] = nd;
                }
            }
            return double.PositiveInfinity;
        }
    }
}
