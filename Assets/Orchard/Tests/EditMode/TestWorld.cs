using System;
using System.Collections.Generic;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using Orchard;

namespace Orchard.Tests
{
    // A deterministic, isolated OrchardGame for EditMode tests.
    //
    // The shipped game builds itself from an empty scene through OrchardBoot. EditMode tests do
    // not run Start(), so this helper attaches the real component to a temporary GameObject and
    // initialises the real fields the AI reads. No production method is reimplemented here.
    public sealed class TestWorld : IDisposable
    {
        public readonly OrchardGame game;
        readonly GameObject host;

        public TestWorld(int seed = 20261117)
        {
            U.SetSeed(seed);
            host = new GameObject("Orchard Test World");
            game = host.AddComponent<OrchardGame>();
            OrchardGame.I = game;

            game.grid = new int[C.GW, C.GH];
            game.baseGrid = (int[,])game.grid.Clone();
            game.reach = new bool[C.GW, C.GH];
            for (int x = 0; x < C.GW; x++)
                for (int y = 0; y < C.GH; y++) game.reach[x, y] = true;

            game.treeCells = new List<Cell>();
            game.trees = new List<TreeEntity>();
            game.enemies = new List<Enemy>();
            game.baits = new List<Bait>();
            game.flyingFruit = new List<FlyingFruit>();
            game.tornados = new List<Tornado>();
            game.logs = new List<FallenLog>();
            game.branches = new List<Branch>();
            game.tufts = new List<Tuft>();
            game.logLines = new List<string>();
            game.spawnQueue = new List<SpawnEvent>();
            game.night = 1;
            game.nightTime = 0;
            game.running = true;

            Pos centre = U.cc(C.GW >> 1, C.GH >> 1);
            game.farmer = new Farmer(centre.x, centre.y);
            game.pip = new Pip(centre.x - C.CELL, centre.y);
            game.thistle = new Thistle(centre.x + C.CELL, centre.y);
            game.thistle.state = ThistleState.Wander;
        }

        // The AI reads the singleton, so tests that keep more than one world alive must say
        // explicitly which world is active.
        public void Activate()
        {
            OrchardGame.I = game;
        }

        public void Dispose()
        {
            if (OrchardGame.I == game) OrchardGame.I = null;
            if (host != null) UnityEngine.Object.DestroyImmediate(host);
            U.ResetRandom();
        }

        // ---------------- map helpers ----------------

        public void Fill(int terrain)
        {
            for (int x = 0; x < C.GW; x++)
                for (int y = 0; y < C.GH; y++) game.grid[x, y] = terrain;
            game.baseGrid = (int[,])game.grid.Clone();
        }

        public void Set(int cx, int cy, int terrain)
        {
            game.grid[cx, cy] = terrain;
            game.baseGrid[cx, cy] = terrain;
        }

        public void Wall(int cx, int fromY, int toY, int terrain = C.HILL)
        {
            for (int y = fromY; y <= toY; y++) Set(cx, y, terrain);
        }

        public TreeEntity AddTree(int cx, int cy, double hp = -1)
        {
            TreeEntity t = new TreeEntity(cx, cy);
            if (hp >= 0) t.hp = hp;
            game.trees.Add(t);
            game.treeCells.Add(new Cell(cx, cy));
            return t;
        }

        // ---------------- actor helpers ----------------

        public Shambler AddShambler(double x, double y)
        {
            Shambler s = new Shambler(x, y);
            game.enemies.Add(s);
            return s;
        }

        public Stalker AddStalker(double x, double y)
        {
            Stalker s = new Stalker(x, y);
            game.enemies.Add(s);
            return s;
        }

        public Bird AddBird(double x, double y, bool bad)
        {
            Bird b = new Bird(x, y, bad);
            game.enemies.Add(b);
            return b;
        }

        public Bait AddBait(double x, double y)
        {
            Bait b = new Bait(x, y);
            game.baits.Add(b);
            return b;
        }

        // ---------------- independent map validation ----------------

        // BFS over the real grid using the same walkability rule as the game (hills, bushes and
        // logs block; mud is walkable). Used by map and gameplay tests instead of trusting the
        // production validator.
        public bool[,] WalkableReach()
        {
            bool[,] seen = new bool[C.GW, C.GH];
            Queue<Cell> q = new Queue<Cell>();
            Cell start = new Cell(C.GW >> 1, C.GH >> 1);
            seen[start.cx, start.cy] = true;
            q.Enqueue(start);
            int[] dx = { 1, -1, 0, 0 };
            int[] dy = { 0, 0, 1, -1 };
            while (q.Count > 0)
            {
                Cell c = q.Dequeue();
                for (int k = 0; k < 4; k++)
                {
                    int nx = c.cx + dx[k], ny = c.cy + dy[k];
                    if (!U.inB(nx, ny) || seen[nx, ny]) continue;
                    int t = game.grid[nx, ny];
                    if (t == C.HILL || t == C.BUSH || t == C.LOG) continue;
                    seen[nx, ny] = true;
                    q.Enqueue(new Cell(nx, ny));
                }
            }
            return seen;
        }

        public int CountTerrain(int terrain)
        {
            int n = 0;
            for (int x = 0; x < C.GW; x++)
                for (int y = 0; y < C.GH; y++) if (game.grid[x, y] == terrain) n++;
            return n;
        }

        // ---------------- reflection for private game flow ----------------

        const BindingFlags PrivateInstance = BindingFlags.Instance | BindingFlags.NonPublic;

        public object Call(string method, params object[] args)
        {
            MethodInfo m = typeof(OrchardGame).GetMethod(method, PrivateInstance);
            Assert.NotNull(m, "Expected private OrchardGame method '" + method + "'");
            try
            {
                return m.Invoke(game, args);
            }
            catch (TargetInvocationException e)
            {
                throw e.InnerException ?? e;
            }
        }

        public T Field<T>(string name)
        {
            FieldInfo f = typeof(OrchardGame).GetField(name, PrivateInstance);
            Assert.NotNull(f, "Expected private OrchardGame field '" + name + "'");
            return (T)f.GetValue(game);
        }
    }
}
