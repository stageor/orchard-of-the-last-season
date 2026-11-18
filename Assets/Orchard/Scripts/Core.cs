using System.Collections.Generic;
using UnityEngine;

namespace Orchard
{
    // every number here is copied 1:1 from the html game
    public static class C
    {
        // landscape board for 16:9: 22 x 16 cells of 44px (968 x 704). whole board fits on screen, no minimap
        public const int GW = 24, GH = 16, CELL = 44, WORLD_W = GW * CELL, WORLD_H = GH * CELL;
        public const int VW = WORLD_W, VH = WORLD_H;
        public const int GRASS = 0, BUSH = 1, HILL = 2, MUD = 3, LOG = 4;   // LOG = fallen log across a path (new each night)
        public const int YELLOW_TARGET = 5;     // scatterlings at the start of the game (they are not replaced)

        public const double TREE_HP = 70, FARMER_SPEED = 165, DOG_SPEED = 175, SCYTHE_RANGE = 72, SCYTHE_DMG = 3.2;
        public const double CATCH_RANGE = 78, NIGHT_LEN = 60;
        public const int TOTAL_NIGHTS = 13;
        public const double TRANS_LEN = 3.4;
        public const double WHIRL_NIGHT = 2;        // shamblers learn the dust whirl from night 2
        public const double WHIRL_SPIN = 1.4;        // seconds 2+ shamblers must circle before the tornado forms
        public const double TORNADO_LIFE = 5.0;      // a tornado spins this long
        public const double CONFUSE_T = 5.0;         // a scatterling caught in it is dizzy this long
        public const double NO_EAT_T = 10.0;         // and cannot eat fruit this long
        public const double WHIRL_COOLDOWN = 16.0;   // a shambler rests this long before whirling again
        public const double FARMER_HP = 10;          // farmer health: forgiving on purpose
        public const double STALKER_DMG = 1;         // one stalker bite
        public const double STALKER_HIT_CD = 1.6;    // a stalker bites at most this often
        public const double FARMER_INVULN = 1.2;     // after any hit the farmer cannot be hit again for this long
        public const double FARMER_REGEN_DELAY = 5;  // seconds without a hit before healing starts
        public const double FARMER_REGEN = 0.5;      // hp per second while healing
        public const double KILL_COOLDOWN = 10.0;  // a bad bird rests this long after catching a scatterling
    }

    // a point in canvas pixels (x right, y down), same as the html canvas.
    // game logic uses 64-bit doubles, exactly like javascript numbers
    public class Pos
    {
        public double x, y;
        public Pos() { }
        public Pos(double x, double y) { this.x = x; this.y = y; }
    }

    public struct Cell
    {
        public int cx, cy;
        public Cell(int cx, int cy) { this.cx = cx; this.cy = cy; }
    }

    // anything that moves and gets clamped inside the board
    public class Mover : Pos
    {
        public double r, vx, vy;
    }

    public class Bait : Pos
    {
        public Bait(double x, double y) : base(x, y) { }
    }

    public class FlyingFruit : Pos
    {
        public double vy, life;
    }

    public class Branch : Pos
    {
        public double a;
    }

    // a fallen log lying across 2 cells (cx, cy) and the next cell to the right or below
    public class FallenLog
    {
        public int cx, cy;
        public bool horiz;
        public double seed;
    }

    // a dust tornado made by shamblers walking in a circle; confuses scatterlings that fly into it
    public class Tornado : Pos
    {
        public double life = C.TORNADO_LIFE, r = C.CELL * 3, spin;
        public HashSet<object> hit = new HashSet<object>();   // each bird is confused once per tornado
        public Tornado(double x, double y) : base(x, y) { }
    }

    public class Tuft : Pos
    {
    }

    public class SpawnEvent
    {
        public string type;
        public int n;
        public double t;
    }

    public static class U
    {
        static System.Random rng = new System.Random();

        // deterministic runs for tests and regression harnesses. the shipped game keeps
        // the unseeded default, so player-facing behaviour is unchanged.
        public static void SetSeed(int seed)
        {
            rng = new System.Random(seed);
        }

        public static void ResetRandom()
        {
            rng = new System.Random();
        }

        // same as Math.random(): 0 <= v < 1
        public static double R()
        {
            return rng.NextDouble(); // 0 <= v < 1, 64-bit like the browser
        }

        public static OrchardGame G
        {
            get { return OrchardGame.I; }
        }

        public static Pos cc(int cx, int cy)
        {
            return new Pos(cx * C.CELL + C.CELL / 2.0, cy * C.CELL + C.CELL / 2.0);
        }

        public static Cell w2c(double x, double y)
        {
            return new Cell((int)System.Math.Floor(x / C.CELL), (int)System.Math.Floor(y / C.CELL));
        }

        public static bool inB(int cx, int cy)
        {
            return cx >= 0 && cy >= 0 && cx < C.GW && cy < C.GH;
        }

        public static int terr(double x, double y)
        {
            Cell c = w2c(x, y);
            if (inB(c.cx, c.cy)) return G.grid[c.cx, c.cy];
            return C.HILL;
        }

        public static bool groundBlocked(int cx, int cy)
        {
            if (!inB(cx, cy)) return true;
            int v = G.grid[cx, cy];
            return v == C.BUSH || v == C.HILL || v == C.LOG;
        }

        // same algorithm as the browser's Math.hypot (v8: scale by the max, kahan-compensated sum),
        // so every distance matches javascript bit for bit
        public static double hypot(double a, double b)
        {
            double x = System.Math.Abs(a), y = System.Math.Abs(b);
            if (double.IsNaN(x) || double.IsNaN(y)) return double.NaN;
            double max = 0;
            if (x > max) max = x;
            if (y > max) max = y;
            if (double.IsPositiveInfinity(max)) return double.PositiveInfinity;
            if (max == 0) return 0;
            double sum = 0, comp = 0;
            double n = x / max;
            double summand = n * n - comp;
            double prelim = sum + summand;
            comp = (prelim - sum) - summand;
            sum = prelim;
            n = y / max;
            summand = n * n - comp;
            prelim = sum + summand;
            comp = (prelim - sum) - summand;
            sum = prelim;
            return System.Math.Sqrt(sum) * max;
        }

        public static double dist(Pos a, Pos b)
        {
            return hypot(a.x - b.x, a.y - b.y);
        }

        public static double clamp(double v, double lo, double hi)
        {
            if (v < lo) return lo;
            if (v > hi) return hi;
            return v;
        }

        public static string season(int n)
        {
            if (n <= 3) return "Early Autumn";
            if (n <= 6) return "Mid Autumn";
            if (n <= 9) return "Late Autumn";
            if (n <= 11) return "First Frost";
            return "Deep Winter";
        }

        public static Pos randSky()
        {
            double x = C.CELL + R() * (C.WORLD_W - C.CELL * 2);
            double y = C.CELL + R() * (C.WORLD_H - C.CELL * 2);
            return new Pos(x, y);
        }

        // javascript Math.round (halves go up), not c# banker's rounding
        public static double jsRound(double v)
        {
            return System.Math.Floor(v + 0.5);
        }

        // ('0'+n).slice(-2)
        public static string two(int n)
        {
            string s = "0" + n;
            return s.Substring(s.Length - 2);
        }

        public static Color hex(int rgb, double a = 1)
        {
            return new Color(((rgb >> 16) & 255) / 255f, ((rgb >> 8) & 255) / 255f, (rgb & 255) / 255f, (float)a);
        }

        public static Color rgba(int r, int g, int b, double a)
        {
            return new Color(r / 255f, g / 255f, b / 255f, (float)a);
        }

        // stable sort, like javascript Array.sort
        public static void StableSort<T>(List<T> list, System.Comparison<T> cmp)
        {
            for (int i = 1; i < list.Count; i++)
            {
                T item = list[i];
                int j = i - 1;
                while (j >= 0 && cmp(list[j], item) > 0)
                {
                    list[j + 1] = list[j];
                    j--;
                }
                list[j + 1] = item;
            }
        }
    }
}
