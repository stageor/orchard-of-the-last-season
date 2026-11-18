using NUnit.Framework;
using Orchard;

namespace Orchard.Tests
{
    // Exercises the real finite state machine in Assets/Orchard/Scripts/ThistleFSM.cs:
    // Wander -> Feed at 6 cells (7 if the enemy is chewing a tree), Feed -> Wander beyond
    // 7.5 cells, Flee at 2 hp, recovery at 4 hp, and the pack rule for shambler retaliation.
    [TestFixture]
    public class ThistleFSMTests
    {
        TestWorld world;
        Thistle thistle;

        [SetUp]
        public void SetUp()
        {
            world = new TestWorld(1618);
            world.Fill(C.GRASS);
            thistle = world.game.thistle;
            thistle.x = 300;
            thistle.y = 300;
            thistle.state = ThistleState.Wander;
            thistle.hp = 5;
            world.game.farmer.x = 900;
            world.game.farmer.y = 300;
        }

        [TearDown]
        public void TearDown()
        {
            world.Dispose();
        }

        [Test]
        public void Thistle_StartsWandering()
        {
            Thistle fresh = new Thistle(500, 500);
            Assert.AreEqual(ThistleState.Wander, fresh.state);
            Assert.AreEqual(5.0, fresh.hp, 1e-12);
        }

        [Test]
        public void Thistle_EntersFeed_WhenEnemyIsWithinSixCells()
        {
            Stalker enemy = world.AddStalker(thistle.x + C.CELL * 5.5, thistle.y);

            thistle.update(0.01);

            Assert.AreEqual(ThistleState.Feed, thistle.state);
            Assert.AreSame(enemy, thistle.target);
        }

        [Test]
        public void Thistle_StaysWandering_WhenEnemyIsOutsideSixCells()
        {
            world.AddStalker(thistle.x + C.CELL * 6.5, thistle.y);

            thistle.update(0.01);

            Assert.AreEqual(ThistleState.Wander, thistle.state);
            Assert.IsNull(thistle.target);
        }

        [Test]
        public void Thistle_PrefersAnEnemyThatIsChewingATree()
        {
            // tree at cell (10,8) -> centre (462, 374)
            world.AddTree(10, 8);
            Stalker farther = world.AddStalker(470, 374);   // 270 px away, 8 px from the tree
            Stalker closer = world.AddStalker(430, 374);    // 230 px away, 32 px from the tree
            thistle.x = 200;
            thistle.y = 374;

            thistle.update(0.01);

            Assert.AreEqual(ThistleState.Feed, thistle.state);
            Assert.AreSame(farther, thistle.target,
                "an enemy within 30 px of a tree counts as 2.5 cells closer");
            Assert.IsNotNull(closer);
        }

        [Test]
        public void Thistle_LeavesFeed_WhenTargetIsBeyondSevenAndAHalfCells()
        {
            Stalker enemy = world.AddStalker(thistle.x + C.CELL * 8, thistle.y);
            thistle.state = ThistleState.Feed;
            thistle.target = enemy;

            thistle.update(0.01);

            Assert.AreEqual(ThistleState.Wander, thistle.state);
            Assert.IsNull(thistle.target);
        }

        [Test]
        public void Thistle_KeepsFeeding_InsideHysteresisBand()
        {
            Stalker enemy = world.AddStalker(thistle.x + C.CELL * 7, thistle.y);
            thistle.state = ThistleState.Feed;
            thistle.target = enemy;

            thistle.update(0.01);

            Assert.AreEqual(ThistleState.Feed, thistle.state);
            Assert.AreSame(enemy, thistle.target);
        }

        [Test]
        public void Thistle_LeavesFeed_WhenTargetDies()
        {
            Stalker enemy = world.AddStalker(thistle.x + C.CELL * 3, thistle.y);
            thistle.state = ThistleState.Feed;
            thistle.target = enemy;
            enemy.dead = true;

            thistle.update(0.01);

            Assert.AreEqual(ThistleState.Wander, thistle.state);
            Assert.IsNull(thistle.target);
        }

        [Test]
        public void Thistle_FleesAtTwoHp_AndRunsToTheFarmer()
        {
            thistle.hp = 2;
            double before = U.dist(thistle, world.game.farmer);

            thistle.update(0.05);

            Assert.AreEqual(ThistleState.Flee, thistle.state);
            Assert.IsNull(thistle.target);
            Assert.Less(U.dist(thistle, world.game.farmer), before);
        }

        [Test]
        public void Thistle_RecoversFromFleeAtFourHp()
        {
            thistle.state = ThistleState.Flee;
            thistle.hp = 4;

            thistle.update(0.01);

            Assert.AreEqual(ThistleState.Wander, thistle.state);
        }

        [Test]
        public void Thistle_AttacksAStalkerInMelee_AndTakesRetaliation()
        {
            Stalker enemy = world.AddStalker(thistle.x + 20, thistle.y);
            enemy.hp = 100;                       // survive a full second so the retaliation is measurable
            thistle.state = ThistleState.Feed;
            thistle.target = enemy;
            double before = thistle.hp;

            Tick(thistle, 1.0);

            Assert.AreEqual(92.0, enemy.hp, 1e-9, "the dog deals 8 damage per second");
            Assert.AreEqual(before - 0.9, thistle.hp, 1e-9, "a stalker fights back one-on-one");
        }

        [Test]
        public void Thistle_KillsANormalStalkerWithinOneSecond()
        {
            Stalker enemy = world.AddStalker(thistle.x + 20, thistle.y);
            thistle.state = ThistleState.Feed;
            thistle.target = enemy;

            Tick(thistle, 1.0);

            Assert.IsTrue(enemy.dead, "8 damage per second kills a 6 hp stalker");
        }

        [Test]
        public void Thistle_DoesNotTakeRetaliationFromAShambler()
        {
            Shambler enemy = world.AddShambler(thistle.x + 20, thistle.y);
            thistle.state = ThistleState.Feed;
            thistle.target = enemy;
            double before = thistle.hp;

            Tick(thistle, 1.0);

            Assert.IsTrue(enemy.dead);
            Assert.AreEqual(before, thistle.hp, 1e-9,
                "shamblers can only hurt her as a pack, handled by OrchardGame.PackBites");
        }

        [Test]
        public void Thistle_DoesNotAttackAtThirtyPixels()
        {
            Stalker enemy = world.AddStalker(thistle.x + 30, thistle.y);
            thistle.state = ThistleState.Feed;
            thistle.target = enemy;

            thistle.update(1.0);

            Assert.AreEqual(6.0, enemy.hp, 1e-12);
            Assert.IsFalse(enemy.dead);
        }

        [Test]
        public void Thistle_IgnoresBirds()
        {
            world.AddBird(thistle.x + 40, thistle.y, false);
            world.AddBird(thistle.x - 40, thistle.y, true);

            thistle.update(0.01);

            Assert.AreEqual(ThistleState.Wander, thistle.state);
            Assert.IsNull(thistle.target);
        }

        [Test]
        public void Thistle_HurtClampsAtZero()
        {
            thistle.Hurt(2);
            Assert.AreEqual(3.0, thistle.hp, 1e-12);
            thistle.Hurt(100);
            Assert.AreEqual(0.0, thistle.hp, 1e-12);
        }

        [Test]
        public void Thistle_WanderPatrolStaysOnTheBoard()
        {
            world.AddTree(5, 5);

            thistle.update(0.01);

            Assert.IsNotNull(thistle.patrol);
            Assert.GreaterOrEqual(thistle.patrol.x, 0);
            Assert.LessOrEqual(thistle.patrol.x, C.WORLD_W);
            Assert.GreaterOrEqual(thistle.patrol.y, 0);
            Assert.LessOrEqual(thistle.patrol.y, C.WORLD_H);
        }

        // Real frames are ~16 ms. A single one-second step would move the dog far past a
        // target 20 px away and the melee check would never run.
        static void Tick(Thistle dog, double seconds, double step = 0.05)
        {
            int n = (int)System.Math.Round(seconds / step);
            for (int i = 0; i < n; i++) dog.update(step);
        }
    }
}
