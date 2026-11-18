using System;
using System.Collections.Generic;
using System.Text;
using NUnit.Framework;
using Orchard;

namespace Orchard.Tests
{
    // Randomised but reproducible regression coverage.
    //
    // PR CI runs a short seed set. The nightly workflow sets ORCHARD_REGRESSION=1 and the same
    // test expands to a much larger seed sweep. Every seed is fixed, so a failure can always be
    // reproduced exactly.
    [TestFixture]
    public class RegressionTests
    {
        static int[] Seeds()
        {
            bool nightly = Environment.GetEnvironmentVariable("ORCHARD_REGRESSION") == "1";
            int count = nightly ? 32 : 8;
            int[] seeds = new int[count];
            for (int i = 0; i < count; i++) seeds[i] = 1000 + i * 7919;
            return seeds;
        }

        [Test]
        public void MapAndNightTerrain_KeepEveryInvariant_AcrossTheSeedSweep()
        {
            foreach (int seed in Seeds())
            {
                using (TestWorld w = new TestWorld(seed))
                {
                    U.SetSeed(seed);
                    MapGenerator.BuildStatic(w.game);
                    AssertStatic(w, seed);

                    U.SetSeed(seed * 3 + 1);
                    MapGenerator.NewNightTerrain(w.game);
                    AssertNight(w, seed);
                }
            }
        }

        [Test]
        public void AiSimulation_IsDeterministicForTheSameSeed()
        {
            int seed = 424242;
            string first = RunSimulation(seed, 240);
            string second = RunSimulation(seed, 240);

            Assert.AreEqual(first, second, "the same seed must produce the same 8 second simulation");
        }

        // 240 fixed steps of the real UpdateGame loop, including spawning, A* navigation,
        // utility decisions, behaviour trees, the FSM, boids and the pack rule.
        static string RunSimulation(int seed, int steps)
        {
            using (TestWorld w = new TestWorld(seed))
            {
                U.SetSeed(seed);
                w.game.night = 2;
                w.Call("StartNight");
                w.game.running = true;
                w.game.spawnQueue.Clear();          // keep the run focused on AI, not wave timing
                w.game.enemies.Clear();

                w.AddShambler(200, 200);
                w.AddShambler(240, 210);
                w.AddShambler(280, 220);
                w.AddStalker(700, 500);
                w.AddStalker(720, 520);
                w.AddBird(500, 200, false);
                w.AddBird(540, 220, false);
                w.AddBird(580, 240, true);

                for (int i = 0; i < steps; i++) w.Call("UpdateGame", 1.0 / 30.0);

                Assert.Greater(w.game.nightTime, 7.9, "the simulation must actually advance");
                Assert.Greater(w.game.enemies.Count, 0, "enemies must survive the simulation");
                Assert.Less(w.game.nightTime, C.NIGHT_LEN, "the night must not end during this test");

                return Snapshot(w.game);
            }
        }

        static string Snapshot(OrchardGame g)
        {
            StringBuilder sb = new StringBuilder();
            sb.Append("nightTime=").Append(g.nightTime.ToString("R"));
            sb.Append("|night=").Append(g.night);
            sb.Append("|fruit=").Append(g.fruitSaved).Append("/").Append(g.fruitLost).Append("/").Append(g.fruitFallen);
            sb.Append("|tornados=").Append(g.tornadoCount).Append("/").Append(g.birdsConfused);
            sb.Append("|farmer=").Append(Pos(g.farmer)).Append(":").Append(g.farmer.hp.ToString("R"));
            sb.Append("|pip=").Append(Pos(g.pip)).Append(":").Append(g.pip.hp.ToString("R")).Append(":").Append(g.pip.retreating);
            sb.Append("|thistle=").Append(Pos(g.thistle)).Append(":").Append(g.thistle.hp.ToString("R")).Append(":").Append(g.thistle.state);
            sb.Append("|trees=");
            foreach (TreeEntity t in g.trees) sb.Append(t.cx).Append(",").Append(t.cy).Append(":").Append(t.hp.ToString("R")).Append(";");
            sb.Append("|enemies=").Append(g.enemies.Count);
            foreach (Enemy e in g.enemies)
                sb.Append("|").Append(e.type).Append(":").Append(Pos(e)).Append(":").Append(e.hp.ToString("R")).Append(":").Append(e.dead);
            sb.Append("|rng=").Append(U.R().ToString("R"));
            return sb.ToString();
        }

        static string Pos(Pos p)
        {
            return p.x.ToString("R") + "," + p.y.ToString("R");
        }

        static void AssertStatic(TestWorld w, int seed)
        {
            Assert.AreEqual(6, w.game.treeCells.Count, "seed " + seed);
            bool[,] reach = w.WalkableReach();
            foreach (Cell t in w.game.treeCells)
                Assert.IsTrue(reach[t.cx, t.cy], "tree unreachable, seed " + seed);

            int left, right, top, bottom;
            EdgeCounts(reach, out left, out right, out top, out bottom);
            Assert.GreaterOrEqual(left, 3, "seed " + seed);
            Assert.GreaterOrEqual(right, 3, "seed " + seed);
            Assert.GreaterOrEqual(top, 3, "seed " + seed);
            Assert.GreaterOrEqual(bottom, 3, "seed " + seed);
        }

        static void AssertNight(TestWorld w, int seed)
        {
            bool[,] reach = w.WalkableReach();
            foreach (Cell t in w.game.treeCells)
                Assert.IsTrue(reach[t.cx, t.cy], "tree unreachable after rain, seed " + seed);
            int left, right, top, bottom;
            EdgeCounts(reach, out left, out right, out top, out bottom);
            Assert.GreaterOrEqual(left, 3, "seed " + seed);
            Assert.GreaterOrEqual(right, 3, "seed " + seed);
            Assert.GreaterOrEqual(top, 3, "seed " + seed);
            Assert.GreaterOrEqual(bottom, 3, "seed " + seed);
            Assert.LessOrEqual(w.game.logs.Count, MapGenerator.LOGS_PER_NIGHT, "seed " + seed);
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
    }
}
