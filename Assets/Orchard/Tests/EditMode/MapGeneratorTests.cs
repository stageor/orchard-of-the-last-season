using System.Collections.Generic;
using NUnit.Framework;
using Orchard;

namespace Orchard.Tests
{
    // Tests the procedural generator and its validator in Assets/Orchard/Scripts/MapGenerator.cs.
    // Reachability is re-checked here with a separate BFS over the real grid, so a broken
    // production validator cannot make these tests pass by accident.
    [TestFixture]
    public class MapGeneratorTests
    {
        static readonly int[] Seeds = { 1, 2, 3, 4, 5, 6, 17, 99 };

        static TestWorld Build(int seed)
        {
            TestWorld w = new TestWorld(seed);
            U.SetSeed(seed);
            MapGenerator.BuildStatic(w.game);
            return w;
        }

        [Test]
        public void BuildStatic_SameSeed_ProducesIdenticalMap()
        {
            int[,] gridA;
            List<Cell> treesA;
            using (TestWorld a = Build(1234))
            {
                gridA = (int[,])a.game.grid.Clone();
                treesA = new List<Cell>(a.game.treeCells);
            }

            using (TestWorld b = Build(1234))
            {
                AssertGridsEqual(gridA, b.game.grid);
                Assert.AreEqual(treesA.Count, b.game.treeCells.Count);
                for (int i = 0; i < treesA.Count; i++) Assert.AreEqual(treesA[i], b.game.treeCells[i]);
            }
        }

        [Test]
        public void BuildStatic_DifferentSeeds_ProduceDifferentMaps()
        {
            int[,] gridA;
            using (TestWorld a = Build(1)) gridA = (int[,])a.game.grid.Clone();
            using (TestWorld b = Build(2))
            {
                bool different = false;
                for (int x = 0; x < C.GW && !different; x++)
                    for (int y = 0; y < C.GH && !different; y++)
                        if (gridA[x, y] != b.game.grid[x, y]) different = true;
                Assert.IsTrue(different, "seeding must actually change the generated layout");
            }
        }

        [Test]
        public void BuildStatic_PlacesSixLivingTreesInsideTheSafeArea()
        {
            foreach (int seed in Seeds)
            {
                using (TestWorld w = Build(seed))
                {
                    Assert.AreEqual(6, w.game.treeCells.Count, "seed " + seed);
                    Assert.AreEqual(6, w.game.trees.Count, "seed " + seed);
                    foreach (TreeEntity t in w.game.trees)
                    {
                        Assert.IsTrue(t.alive, "seed " + seed);
                        Assert.AreEqual(C.TREE_HP, t.hp, 1e-12);
                        Assert.AreEqual(C.TREE_HP, t.maxhp, 1e-12);
                        Assert.AreEqual(4, t.fruit);
                        Assert.AreEqual(C.GRASS, w.game.grid[t.cx, t.cy], "trees sit on grass, seed " + seed);
                        Assert.GreaterOrEqual(t.cx, 2, "seed " + seed);
                        Assert.LessOrEqual(t.cx, C.GW - 3, "seed " + seed);
                        Assert.GreaterOrEqual(t.cy, 2, "seed " + seed);
                        Assert.LessOrEqual(t.cy, C.GH - 3, "seed " + seed);
                        int dx = t.cx - (C.GW >> 1), dy = t.cy - (C.GH >> 1);
                        Assert.IsFalse(System.Math.Abs(dx) <= 1 && System.Math.Abs(dy) <= 1,
                            "trees must not spawn on the farmer, seed " + seed);
                    }

                    for (int i = 0; i < w.game.treeCells.Count; i++)
                        for (int j = i + 1; j < w.game.treeCells.Count; j++)
                        {
                            Cell a = w.game.treeCells[i], b = w.game.treeCells[j];
                            Assert.GreaterOrEqual(System.Math.Abs(a.cx - b.cx) + System.Math.Abs(a.cy - b.cy), 3,
                                "trees must not crowd each other, seed " + seed);
                        }
                }
            }
        }

        [Test]
        public void BuildStatic_EveryTreeIsReachableAndEverySideIsOpen()
        {
            foreach (int seed in Seeds)
            {
                using (TestWorld w = Build(seed))
                {
                    AssertValidStaticMap(w, "seed " + seed);
                }
            }
        }

        [Test]
        public void BuildStatic_CentreIsClearOfHillsAndBushes()
        {
            foreach (int seed in Seeds)
            {
                using (TestWorld w = Build(seed))
                {
                    int cx = C.GW >> 1, cy = C.GH >> 1;
                    for (int dx = -1; dx <= 1; dx++)
                        for (int dy = -1; dy <= 1; dy++)
                        {
                            int v = w.game.grid[cx + dx, cy + dy];
                            Assert.AreNotEqual(C.HILL, v, "seed " + seed);
                            Assert.AreNotEqual(C.BUSH, v, "seed " + seed);
                        }
                }
            }
        }

        [Test]
        public void NewNightTerrain_KeepsTheStaticHillsAndBushes()
        {
            using (TestWorld w = Build(42))
            {
                int[,] staticLayout = (int[,])w.game.grid.Clone();
                U.SetSeed(777);
                MapGenerator.NewNightTerrain(w.game);

                for (int x = 0; x < C.GW; x++)
                    for (int y = 0; y < C.GH; y++)
                    {
                        int before = staticLayout[x, y];
                        if (before == C.HILL || before == C.BUSH)
                            Assert.AreEqual(before, w.game.grid[x, y], "static terrain at " + x + "," + y);
                    }
            }
        }

        [Test]
        public void NewNightTerrain_AddsMudAndKeepsTreesOnGrass()
        {
            using (TestWorld w = Build(42))
            {
                U.SetSeed(777);
                MapGenerator.NewNightTerrain(w.game);

                Assert.Greater(w.CountTerrain(C.MUD), 0, "the rain must create mud puddles");
                foreach (Cell t in w.game.treeCells)
                    Assert.AreEqual(C.GRASS, w.game.grid[t.cx, t.cy], "trees never sit on mud");
            }
        }

        [Test]
        public void NewNightTerrain_IsDeterministicForSameSeed()
        {
            int[,] gridA;
            List<string> logsA;
            using (TestWorld a = Build(55))
            {
                U.SetSeed(9001);
                MapGenerator.NewNightTerrain(a.game);
                gridA = (int[,])a.game.grid.Clone();
                logsA = DescribeLogs(a.game.logs);
            }

            using (TestWorld b = Build(55))
            {
                U.SetSeed(9001);
                MapGenerator.NewNightTerrain(b.game);
                AssertGridsEqual(gridA, b.game.grid);
                CollectionAssert.AreEqual(logsA, DescribeLogs(b.game.logs));
            }
        }

        [Test]
        public void NewNightTerrain_LeavesTheMapValidForEveryTreeAndSide()
        {
            foreach (int seed in Seeds)
            {
                using (TestWorld w = Build(seed))
                {
                    U.SetSeed(seed * 31 + 7);
                    MapGenerator.NewNightTerrain(w.game);

                    bool[,] reach = w.WalkableReach();
                    foreach (Cell t in w.game.treeCells)
                        Assert.IsTrue(reach[t.cx, t.cy], "tree unreachable after night terrain, seed " + seed);

                    int left, right, top, bottom;
                    EdgeCounts(reach, out left, out right, out top, out bottom);
                    Assert.GreaterOrEqual(left, 3, "seed " + seed);
                    Assert.GreaterOrEqual(right, 3, "seed " + seed);
                    Assert.GreaterOrEqual(top, 3, "seed " + seed);
                    Assert.GreaterOrEqual(bottom, 3, "seed " + seed);

                    foreach (Cell t in w.game.treeCells)
                    {
                        int open = 0;
                        for (int dx = -1; dx <= 1; dx++)
                            for (int dy = -1; dy <= 1; dy++)
                            {
                                if (dx == 0 && dy == 0) continue;
                                int x = t.cx + dx, y = t.cy + dy;
                                if (U.inB(x, y) && reach[x, y]) open++;
                            }
                        Assert.GreaterOrEqual(open, 4, "tree boxed in after night terrain, seed " + seed);
                    }
                }
            }
        }

        [Test]
        public void FallenLogs_HaveAValidTwoCellFootprint_AndAvoidTreesAndTheCentre()
        {
            foreach (int seed in Seeds)
            {
                using (TestWorld w = Build(seed))
                {
                    U.SetSeed(seed * 131 + 3);
                    MapGenerator.NewNightTerrain(w.game);

                    Assert.LessOrEqual(w.game.logs.Count, MapGenerator.LOGS_PER_NIGHT, "seed " + seed);
                    foreach (FallenLog log in w.game.logs)
                    {
                        Assert.AreEqual(C.LOG, w.game.grid[log.cx, log.cy], "seed " + seed);
                        int bx = log.horiz ? log.cx + 1 : log.cx;
                        int by = log.horiz ? log.cy : log.cy + 1;
                        Assert.AreEqual(C.LOG, w.game.grid[bx, by], "second half of the log, seed " + seed);

                        int scx = C.GW >> 1, scy = C.GH >> 1;
                        Assert.IsFalse(System.Math.Abs(log.cx - scx) <= 2 && System.Math.Abs(log.cy - scy) <= 2,
                            "a log must not trap the farmer at spawn, seed " + seed);
                        foreach (Cell t in w.game.treeCells)
                        {
                            Assert.IsFalse(System.Math.Abs(t.cx - log.cx) <= 1 && System.Math.Abs(t.cy - log.cy) <= 1,
                                "a log must not touch a tree, seed " + seed);
                        }
                    }

                    for (int i = 0; i < w.game.logs.Count; i++)
                        for (int j = i + 1; j < w.game.logs.Count; j++)
                        {
                            FallenLog a = w.game.logs[i], b = w.game.logs[j];
                            Assert.Greater(System.Math.Abs(a.cx - b.cx) + System.Math.Abs(a.cy - b.cy), 1,
                                "log footprints must not overlap, seed " + seed);
                        }
                }
            }
        }

        [Test]
        public void NewNightTerrain_KeepsTheCentreFreeOfMud()
        {
            using (TestWorld w = Build(42))
            {
                U.SetSeed(777);
                MapGenerator.NewNightTerrain(w.game);
                int cx = C.GW >> 1, cy = C.GH >> 1;
                for (int dx = -1; dx <= 1; dx++)
                    for (int dy = -1; dy <= 1; dy++)
                        Assert.AreNotEqual(C.MUD, w.game.grid[cx + dx, cy + dy]);
            }
        }

        // ---------------- helpers ----------------

        static void AssertValidStaticMap(TestWorld w, string label)
        {
            bool[,] reach = w.WalkableReach();
            foreach (Cell t in w.game.treeCells)
                Assert.IsTrue(reach[t.cx, t.cy], "tree unreachable, " + label);

            int left, right, top, bottom;
            EdgeCounts(reach, out left, out right, out top, out bottom);
            Assert.GreaterOrEqual(left, 3, "left edge sealed, " + label);
            Assert.GreaterOrEqual(right, 3, "right edge sealed, " + label);
            Assert.GreaterOrEqual(top, 3, "top edge sealed, " + label);
            Assert.GreaterOrEqual(bottom, 3, "bottom edge sealed, " + label);

            foreach (Cell t in w.game.treeCells)
            {
                int open = 0;
                for (int dx = -1; dx <= 1; dx++)
                    for (int dy = -1; dy <= 1; dy++)
                    {
                        if (dx == 0 && dy == 0) continue;
                        int x = t.cx + dx, y = t.cy + dy;
                        if (U.inB(x, y) && reach[x, y]) open++;
                    }
                Assert.GreaterOrEqual(open, 4, "tree boxed in, " + label);
            }
        }

        static void EdgeCounts(bool[,] reach, out int left, out int right, out int top, out int bottom)
        {
            left = right = top = bottom = 0;
            for (int i = 0; i < C.GH; i++)
            {
                if (reach[0, i]) left++;
                if (reach[C.GW - 1, i]) right++;
            }
            for (int i = 0; i < C.GW; i++)
            {
                if (reach[i, 0]) top++;
                if (reach[i, C.GH - 1]) bottom++;
            }
        }

        static void AssertGridsEqual(int[,] expected, int[,] actual)
        {
            Assert.AreEqual(expected.GetLength(0), actual.GetLength(0));
            Assert.AreEqual(expected.GetLength(1), actual.GetLength(1));
            for (int x = 0; x < expected.GetLength(0); x++)
                for (int y = 0; y < expected.GetLength(1); y++)
                    Assert.AreEqual(expected[x, y], actual[x, y], "cell " + x + "," + y);
        }

        static List<string> DescribeLogs(List<FallenLog> logs)
        {
            List<string> s = new List<string>();
            foreach (FallenLog l in logs) s.Add(l.cx + ":" + l.cy + ":" + (l.horiz ? "h" : "v"));
            return s;
        }
    }
}
