using NUnit.Framework;
using Orchard;

namespace Orchard.Tests
{
    // Exercises the production behaviour tree in Assets/Orchard/Scripts/PipBehaviourTree.cs.
    // The tree's structure is tested through its public nodes, and Pip's behaviour is tested
    // through the real update() tick (no action logic is duplicated here).
    [TestFixture]
    public class PipBehaviourTreeTests
    {
        TestWorld world;
        Pip pip;

        [SetUp]
        public void SetUp()
        {
            world = new TestWorld(2468);
            world.Fill(C.GRASS);
            pip = world.game.pip;
            pip.x = 100;
            pip.y = 300;
            pip.hp = 5;
            world.game.farmer.x = 900;
            world.game.farmer.y = 300;
        }

        [TearDown]
        public void TearDown()
        {
            world.Dispose();
        }

        // ---------------- behaviour tree framework ----------------

        [Test]
        public void Selector_ReturnsFirstNonFailure_AndStopsTicking()
        {
            int calls = 0;
            BTSelector selector = new BTSelector(new BTNode[]
            {
                new BTAction(() => { calls++; return BTStatus.Failure; }),
                new BTAction(() => { calls++; return BTStatus.Running; }),
                new BTAction(() => { calls++; return BTStatus.Success; })
            });

            Assert.AreEqual(BTStatus.Running, selector.Tick());
            Assert.AreEqual(2, calls);
        }

        [Test]
        public void Selector_FailsWhenEveryChildFails()
        {
            BTSelector selector = new BTSelector(new BTNode[]
            {
                new BTAction(() => BTStatus.Failure),
                new BTAction(() => BTStatus.Failure)
            });

            Assert.AreEqual(BTStatus.Failure, selector.Tick());
        }

        [Test]
        public void Sequence_StopsAtFirstNonSuccess()
        {
            int calls = 0;
            BTSequence sequence = new BTSequence(new BTNode[]
            {
                new BTAction(() => { calls++; return BTStatus.Success; }),
                new BTAction(() => { calls++; return BTStatus.Failure; }),
                new BTAction(() => { calls++; return BTStatus.Success; })
            });

            Assert.AreEqual(BTStatus.Failure, sequence.Tick());
            Assert.AreEqual(2, calls);
        }

        [Test]
        public void Sequence_SucceedsWhenEveryChildSucceeds()
        {
            BTSequence sequence = new BTSequence(new BTNode[]
            {
                new BTAction(() => BTStatus.Success),
                new BTAction(() => BTStatus.Success)
            });

            Assert.AreEqual(BTStatus.Success, sequence.Tick());
        }

        [Test]
        public void EmptySelectorFails_EmptySequenceSucceeds()
        {
            Assert.AreEqual(BTStatus.Failure, new BTSelector(new BTNode[0]).Tick());
            Assert.AreEqual(BTStatus.Success, new BTSequence(new BTNode[0]).Tick());
        }

        // ---------------- Pip target selection ----------------

        [Test]
        public void WeakestTree_PicksTheLowestHealthFraction()
        {
            TreeEntity strong = world.AddTree(3, 3, 63);     // 90%
            TreeEntity weak = world.AddTree(6, 3, 35);       // 50%

            Assert.AreSame(weak, pip.weakestTree());
            Assert.IsNotNull(strong);
        }

        [Test]
        public void WeakestTree_IgnoresDeadTrees()
        {
            TreeEntity dead = world.AddTree(3, 3, 1);
            dead.alive = false;
            world.AddTree(6, 3, 70);

            Assert.IsNull(pip.weakestTree());
        }

        [Test]
        public void WeakestTree_TieBreaksByFirstHit()
        {
            TreeEntity later = world.AddTree(3, 3, 35);
            later.firstHit = 10;
            TreeEntity earlier = world.AddTree(6, 3, 35);
            earlier.firstHit = 2;

            Assert.AreSame(earlier, pip.weakestTree());
        }

        [Test]
        public void WeakestTree_ReturnsNullWhenEverythingIsHealthy()
        {
            world.AddTree(3, 3, 70);
            world.AddTree(6, 3, 70);

            Assert.IsNull(pip.weakestTree());
        }

        [Test]
        public void WeakestTree_CommitsToCurrentRepair_UnlessAnotherIsClearlyWeaker()
        {
            TreeEntity current = world.AddTree(3, 3, 42);    // 60%
            TreeEntity other = world.AddTree(6, 3, 35);      // 50%, only 10 points lower
            pip.target = current;

            Assert.AreSame(current, pip.weakestTree(), "a 10% difference must not restart the repair");

            other.hp = 28;                                   // 40%, 20 points lower
            Assert.AreSame(other, pip.weakestTree(), "a >15% difference must switch to the weaker tree");
        }

        // ---------------- Pip actions ----------------

        [Test]
        public void Pip_RepairsTheWeakestTree_ThenReleasesTheTarget()
        {
            TreeEntity tree = world.AddTree(5, 5, 60);
            pip.x = tree.x;
            pip.y = tree.y;

            pip.update(0.5);

            Assert.AreSame(tree, pip.target);
            Assert.AreEqual(62.5, tree.hp, 1e-9, "5 hp per second for half a second");
            Assert.IsTrue(world.game.logLines.Exists(l => l.Contains("weakest tree")));

            tree.hp = 69.5;
            pip.update(0.5);

            Assert.AreEqual(tree.maxhp, tree.hp, 1e-9);
            Assert.IsNull(pip.target, "the job is finished");
        }

        [Test]
        public void Pip_DoesNotRepairWhenNoTreeIsDamaged_AndFollowsTheFarmer()
        {
            world.AddTree(3, 3, 70);
            world.AddTree(6, 3, 70);
            double before = U.dist(pip, world.game.farmer);

            pip.update(0.5);

            Assert.IsNull(pip.target);
            Assert.Less(U.dist(pip, world.game.farmer), before);
        }

        [Test]
        public void Pip_StopsFollowingInsideOneCell()
        {
            world.game.farmer.x = pip.x + 30;
            world.game.farmer.y = pip.y;
            double beforeX = pip.x;

            pip.update(0.5);

            Assert.AreEqual(beforeX, pip.x, 1e-9, "inside the stop radius Pip stands still");
        }

        [Test]
        public void Pip_RunsToTheFarmerWhenHurt_AndAbandonsTheRepair()
        {
            TreeEntity tree = world.AddTree(5, 5, 20);
            pip.x = 100;
            pip.y = 300;
            pip.hp = 2;
            double before = U.dist(pip, world.game.farmer);

            pip.update(0.1);

            Assert.IsTrue(pip.retreating);
            Assert.IsNull(pip.target);
            Assert.Less(U.dist(pip, world.game.farmer), before);
            Assert.IsNotNull(tree);
        }

        [Test]
        public void Pip_RetreatUsesHysteresis()
        {
            pip.hp = 2;
            pip.update(0.01);
            Assert.IsTrue(pip.retreating);

            pip.hp = 4.4;
            pip.update(0.01);
            Assert.IsTrue(pip.retreating, "must stay retreating below 4.5 hp");

            pip.hp = 4.6;
            pip.update(0.01);
            Assert.IsFalse(pip.retreating, "must recover at 4.5 hp");
        }

        [Test]
        public void Pip_HealsSlowlyWhenNotRetreating()
        {
            world.game.farmer.x = pip.x + 30;
            world.game.farmer.y = pip.y;
            pip.hp = 3;

            pip.update(1.0);

            Assert.AreEqual(3.15, pip.hp, 1e-9);
        }

        [Test]
        public void Pip_DoesNotHealNaturallyWhileRetreating()
        {
            pip.hp = 2;
            pip.x = 100;
            pip.y = 300;
            pip.update(0.01);
            Assert.IsTrue(pip.retreating);

            pip.hp = 2.4;
            pip.update(0.1);

            Assert.IsTrue(pip.retreating);
            Assert.AreEqual(2.4, pip.hp, 1e-9, "natural recovery is suspended during a retreat");
        }

        [Test]
        public void Pip_HurtClampsAtZero()
        {
            pip.hp = 1;
            pip.Hurt(5);

            Assert.AreEqual(0.0, pip.hp, 1e-12);
            Assert.Greater(pip.hurtFlash, 0);
        }
    }
}
