import shutil

from Dataset import *


def visualize(model_name="Pix2PixConditionalGAN", named_images=None, save_path=None):
    if not os.path.exists(save_path):
        os.makedirs(save_path)
    # 이미지 y축 방향으로 붙이기
    image = np.hstack(named_images[1:])
    # 이미지 스케일 바꾸기(~1 ~ 1 -> 0~ 255)
    image = ((image + 1) * 127.5).astype(np.uint8)
    # RGB로 바꾸기
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    cv2.imwrite(os.path.join(save_path, '{}_{}.png'.format(model_name, named_images[0])), image)
    print("{}_{}.png saved in {} folder".format(model_name, named_images[0], save_path))


# 1. tf.data.Dataset의 이점을 이용하지만, 그래프를 저장하지 않는다.
def model(TEST=False, AtoB=True, DB_name="facades", use_TFRecord=True, distance_loss="L1",
          distance_loss_weight=100, optimizer_selection="Adam",
          beta1=0.5, beta2=0.999,  # for Adam optimizer
          decay=0.999, momentum=0.9,  # for RMSProp optimizer
          # batch_size는 1~10사이로 하자
          image_pool=True,  # discriminator 업데이트시 이전에 generator로 부터 생성된 이미지의 사용 여부
          image_pool_size=50,  # image_pool=True 라면 몇개를 사용 할지?
          learning_rate=0.0002, training_epochs=200, batch_size=1, display_step=1, Dropout_rate=0.5,
          using_moving_variable=False,  # using_moving_variable - 이동 평균, 이동 분산을 사용할지 말지 결정하는 변수
          training_size=(256, 256),  # 학습할 때 입력의 크기
          inference_size=(512, 512),  # 테스트 시 inference 해 볼 크기
          save_path="translated_image"):  # 학습 완료 후 변환된 이미지가 저장될 폴더
    if distance_loss == "L1":
        print("target generative GAN with L1 loss")
        model_name = "Pix2PixL1loss"
    elif distance_loss == "L2":
        print("target generative GAN with L1 loss")
        model_name = "Pix2PixL2loss"
    else:
        print("target generative GAN")
        model_name = "Pix2PixGAN"

    # DB 이름도 추가
    if AtoB:
        model_name = "AtoB" + model_name
    else:
        model_name = "BtoA" + model_name

    model_name = DB_name + model_name

    if batch_size == 1:
        norm_selection = "instance_norm"
        model_name = "in" + model_name
    else:
        norm_selection = "batch_norm"
        model_name = "bn_" + model_name

    if TEST == False:
        if os.path.exists("tensorboard/{}".format(model_name)):
            shutil.rmtree("tensorboard/{}".format(model_name))

    # stride? -> [1, 2, 2, 1] = [one image, width, height, one channel]
    def conv2d(input, weight_shape=None, bias_shape=None, norm_selection=None,
               strides=[1, 1, 1, 1], padding="VALID"):

        # weight_init = tf.contrib.layers.xavier_initializer(uniform=False)
        weight_init = tf.random_normal_initializer(mean=0.0, stddev=0.02)
        bias_init = tf.constant_initializer(value=0)

        weight_decay = tf.constant(0, dtype=tf.float32)
        w = tf.get_variable("w", weight_shape, initializer=weight_init,
                            regularizer=tf.contrib.layers.l2_regularizer(scale=weight_decay))

        b = tf.get_variable("b", bias_shape, initializer=bias_init)
        conv_out = tf.nn.conv2d(input, w, strides=strides, padding=padding)

        # batch_norm을 적용하면 bias를 안써도 된다곤 하지만, 나는 썼다.
        if norm_selection == "batch_norm":
            if TEST and using_moving_variable:
                return tf.layers.batch_normalization(tf.nn.bias_add(conv_out, b), training=not TEST)
            else:
                return tf.layers.batch_normalization(tf.nn.bias_add(conv_out, b), training=TEST)
        elif norm_selection == "instance_norm":
            return tf.contrib.layers.instance_norm(tf.nn.bias_add(conv_out, b))
        else:
            return tf.nn.bias_add(conv_out, b)

    def conv2d_transpose(input, output_shape=None, weight_shape=None, bias_shape=None, norm_selection=None,
                         strides=[1, 1, 1, 1], padding="VALID"):

        weight_init = tf.random_normal_initializer(mean=0.0, stddev=0.02)
        bias_init = tf.constant_initializer(value=0)
        weight_decay = tf.constant(0, dtype=tf.float32)

        w = tf.get_variable("w", weight_shape, initializer=weight_init,
                            regularizer=tf.contrib.layers.l2_regularizer(scale=weight_decay))
        b = tf.get_variable("b", bias_shape, initializer=bias_init)

        conv_out = tf.nn.conv2d_transpose(input, w, output_shape=output_shape, strides=strides, padding=padding)

        # batch_norm을 적용하면 bias를 안써도 된다곤 하지만, 나는 썼다.
        if norm_selection == "batch_norm":
            if TEST and using_moving_variable:
                return tf.layers.batch_normalization(tf.nn.bias_add(conv_out, b), training=not TEST)
            else:
                return tf.layers.batch_normalization(tf.nn.bias_add(conv_out, b), training=TEST)
        elif norm_selection == "instance_norm":
            return tf.contrib.layers.instance_norm(tf.nn.bias_add(conv_out, b))
        else:
            return tf.nn.bias_add(conv_out, b)

    # 유넷 - U-NET
    def generator(images=None):

        '''encoder의 활성화 함수는 모두 leaky_relu이며, decoder의 활성화 함수는 모두 relu이다.
        encoder의 첫번째 층에는 batch_norm이 적용 안된다.

        총 16개의 층이다.
        '''

        with tf.variable_scope("Generator"):
            with tf.variable_scope("encoder"):
                with tf.variable_scope("conv1"):
                    conv1 = conv2d(images, weight_shape=(4, 4, images.get_shape()[-1], 64), bias_shape=(64),
                                   strides=[1, 2, 2, 1], padding="SAME")
                    # result shape = (batch_size, 128, 128, 64)
                with tf.variable_scope("conv2"):
                    conv2 = conv2d(tf.nn.leaky_relu(conv1, alpha=0.2), weight_shape=(4, 4, 64, 128), bias_shape=(128),
                                   norm_selection=norm_selection,
                                   strides=[1, 2, 2, 1], padding="SAME")
                    # result shape = (batch_size, 64, 64, 128)
                with tf.variable_scope("conv3"):
                    conv3 = conv2d(tf.nn.leaky_relu(conv2, alpha=0.2), weight_shape=(4, 4, 128, 256), bias_shape=(256),
                                   norm_selection=norm_selection,
                                   strides=[1, 2, 2, 1], padding="SAME")
                    # result shape = (batch_size, 32, 32, 256)
                with tf.variable_scope("conv4"):
                    conv4 = conv2d(tf.nn.leaky_relu(conv3, alpha=0.2), weight_shape=(4, 4, 256, 512), bias_shape=(512),
                                   norm_selection=norm_selection,
                                   strides=[1, 2, 2, 1], padding="SAME")
                    # result shape = (batch_size, 16, 16, 512)
                with tf.variable_scope("conv5"):
                    conv5 = conv2d(tf.nn.leaky_relu(conv4, alpha=0.2), weight_shape=(4, 4, 512, 512), bias_shape=(512),
                                   norm_selection=norm_selection,
                                   strides=[1, 2, 2, 1], padding="SAME")
                    # result shape = (batch_size, 8, 8, 512)
                with tf.variable_scope("conv6"):
                    conv6 = conv2d(tf.nn.leaky_relu(conv5, alpha=0.2), weight_shape=(4, 4, 512, 512), bias_shape=(512),
                                   norm_selection=norm_selection,
                                   strides=[1, 2, 2, 1], padding="SAME")
                    # result shape = (batch_size, 4, 4, 512)
                with tf.variable_scope("conv7"):
                    conv7 = conv2d(tf.nn.leaky_relu(conv6, alpha=0.2), weight_shape=(4, 4, 512, 512), bias_shape=(512),
                                   norm_selection=norm_selection,
                                   strides=[1, 2, 2, 1], padding="SAME")
                    # result shape = (batch_size, 2, 2, 512)
                with tf.variable_scope("conv8"):
                    conv8 = conv2d(tf.nn.leaky_relu(conv7, alpha=0.2), weight_shape=(4, 4, 512, 512), bias_shape=(512),
                                   strides=[1, 2, 2, 1], padding="SAME")
                    # result shape = (batch_size, 1, 1, 512)

            with tf.variable_scope("decoder"):
                with tf.variable_scope("trans_conv1"):
                    '''output_shape = tf.shape(conv2) ???
                    output_shape 을 직접 지정 해주는 경우 예를 들어 (batch_size, 2, 2, 512) 이런식으로 지정해준다면,
                    trans_conv1 의 결과는 무조건 (batch_size, 2, 2, 512) 이어야 한다. 그러나 tf.shape(conv2)로 쓸 경우
                    나중에 session에서 실행될 때 입력이 되므로, batch_size에 종속되지 않는다. 
                    어쨌든 output_shape = tf.shape(conv2) 처럼 코딩하는게 무조건 좋다. 
                    '''
                    trans_conv1 = tf.nn.dropout(
                        conv2d_transpose(tf.nn.relu(conv8), output_shape=tf.shape(conv7), weight_shape=(4, 4, 512, 512),
                                         bias_shape=(512), norm_selection=norm_selection,
                                         strides=[1, 2, 2, 1], padding="SAME"), keep_prob=Dropout_rate)
                    # result shape = (batch_size, 2, 2, 512)
                    # 주의 : 활성화 함수 들어가기전의 encoder 요소를 concat 해줘야함
                    trans_conv1 = tf.concat([trans_conv1, conv7], axis=-1)
                    # result shape = (batch_size, 2, 2, 1024)

                with tf.variable_scope("trans_conv2"):
                    trans_conv2 = tf.nn.dropout(
                        conv2d_transpose(tf.nn.relu(trans_conv1), output_shape=tf.shape(conv6),
                                         weight_shape=(4, 4, 512, 1024),
                                         bias_shape=(512), norm_selection=norm_selection,
                                         strides=[1, 2, 2, 1], padding="SAME"), keep_prob=Dropout_rate)
                    trans_conv2 = tf.concat([trans_conv2, conv6], axis=-1)
                    # result shape = (batch_size, 4, 4, 1024)

                with tf.variable_scope("trans_conv3"):
                    trans_conv3 = tf.nn.dropout(
                        conv2d_transpose(tf.nn.relu(trans_conv2), output_shape=tf.shape(conv5),
                                         weight_shape=(4, 4, 512, 1024),
                                         bias_shape=(512), norm_selection=norm_selection,
                                         strides=[1, 2, 2, 1], padding="SAME"), keep_prob=Dropout_rate)
                    trans_conv3 = tf.concat([trans_conv3, conv5], axis=-1)
                    # result shape = (batch_size, 8, 8, 1024)

                with tf.variable_scope("trans_conv4"):
                    trans_conv4 = conv2d_transpose(tf.nn.relu(trans_conv3), output_shape=tf.shape(conv4),
                                                   weight_shape=(4, 4, 512, 1024),
                                                   bias_shape=(512), norm_selection=norm_selection,
                                                   strides=[1, 2, 2, 1], padding="SAME")
                    trans_conv4 = tf.concat([trans_conv4, conv4], axis=-1)
                    # result shape = (batch_size, 16, 16, 1024)
                with tf.variable_scope("trans_conv5"):
                    trans_conv5 = conv2d_transpose(tf.nn.relu(trans_conv4), output_shape=tf.shape(conv3),
                                                   weight_shape=(4, 4, 256, 1024),
                                                   bias_shape=(256), norm_selection=norm_selection,
                                                   strides=[1, 2, 2, 1], padding="SAME")
                    trans_conv5 = tf.concat([trans_conv5, conv3], axis=-1)
                    # result shape = (batch_size, 32, 32, 512)
                with tf.variable_scope("trans_conv6"):
                    trans_conv6 = conv2d_transpose(tf.nn.relu(trans_conv5), output_shape=tf.shape(conv2),
                                                   weight_shape=(4, 4, 128, 512),
                                                   bias_shape=(128), norm_selection=norm_selection,
                                                   strides=[1, 2, 2, 1], padding="SAME")
                    trans_conv6 = tf.concat([trans_conv6, conv2], axis=-1)
                    # result shape = (batch_size, 64, 64, 256)
                with tf.variable_scope("trans_conv7"):
                    trans_conv7 = conv2d_transpose(tf.nn.relu(trans_conv6), output_shape=tf.shape(conv1),
                                                   weight_shape=(4, 4, 64, 256),
                                                   bias_shape=(64), norm_selection=norm_selection,
                                                   strides=[1, 2, 2, 1], padding="SAME")
                    trans_conv7 = tf.concat([trans_conv7, conv1], axis=-1)
                    # result shape = (batch_size, 128, 128, 128)
                with tf.variable_scope("trans_conv8"):
                    output = tf.nn.tanh(
                        conv2d_transpose(tf.nn.relu(trans_conv7), output_shape=tf.shape(target),
                                         weight_shape=(4, 4, 3, 128),
                                         bias_shape=(3),
                                         strides=[1, 2, 2, 1], padding="SAME"))
                    # result shape = (batch_size, 256, 256, 3)
        return output

    # PatchGAN
    def discriminator(images=None, condition=None):

        '''discriminator의 활성화 함수는 모두 leaky_relu이다.
        genertor와 마찬가지로 첫번째 층에는 batch_norm을 적용 안한다.

        왜 이런 구조를 사용? 아래의 구조 출력단의 ReceptiveField 크기를 구해보면 70이다.(ReceptiveFieldArithmetic/rf.py 에서 구해볼 수 있다.)'''
        conditional_input = tf.concat([images, condition], axis=-1)
        with tf.variable_scope("Discriminator"):
            with tf.variable_scope("conv1"):
                conv1 = tf.nn.leaky_relu(
                    conv2d(conditional_input, weight_shape=(4, 4, conditional_input.get_shape()[-1], 64),
                           bias_shape=(64),
                           strides=[1, 2, 2, 1], padding="SAME"), alpha=0.2)
                # result shape = (batch_size, 128, 128, 64)
            with tf.variable_scope("conv2"):
                conv2 = tf.nn.leaky_relu(
                    conv2d(conv1, weight_shape=(4, 4, 64, 128), bias_shape=(128), norm_selection=norm_selection,
                           strides=[1, 2, 2, 1], padding="SAME"), alpha=0.2)
                # result shape = (batch_size, 64, 64, 128)
            with tf.variable_scope("conv3"):
                conv3 = conv2d(conv2, weight_shape=(4, 4, 128, 256), bias_shape=(256), norm_selection=norm_selection,
                               strides=[1, 2, 2, 1], padding="SAME")
                # result shape = (batch_size, 32, 32, 256)
                conv3 = tf.nn.leaky_relu(
                    tf.pad(conv3, [[0, 0], [1, 1], [1, 1], [0, 0]], mode="CONSTANT", constant_values=0), alpha=0.2)
                # result shape = (batch_size, 34, 34, 256)
            with tf.variable_scope("conv4"):
                conv4 = conv2d(conv3, weight_shape=(4, 4, 256, 512), bias_shape=(512), norm_selection=norm_selection,
                               strides=[1, 1, 1, 1], padding="VALID")
                # result shape = (batch_size, 31, 31, 256)
                conv4 = tf.nn.leaky_relu(
                    tf.pad(conv4, [[0, 0], [1, 1], [1, 1], [0, 0]], mode="CONSTANT", constant_values=0), alpha=0.2)
                # result shape = (batch_size, 33, 33, 512)
            with tf.variable_scope("output"):
                output = conv2d(conv4, weight_shape=(4, 4, 512, 1), bias_shape=(1),
                                strides=[1, 1, 1, 1], padding="VALID")
                # result shape = (batch_size, 30, 30, 1)
            return output, tf.nn.sigmoid(output)

    def training(cost, var_list, scope=None):
        if scope == None:
            tf.summary.scalar("Discriminator Loss", cost)
        else:
            tf.summary.scalar("Generator Loss", cost)

        '''GAN 구현시 Batch Normalization을 쓸 때 주의할 점!!!
        #scope를 써줘야 한다. - 그냥 tf.get_collection(tf.GraphKeys.UPDATE_OPS) 이렇게 써버리면 
        shared_variables 아래에 있는 변수들을 다 업데이트 해야하므로 scope를 지정해줘야한다.
        - GAN의 경우 예)discriminator의 optimizer는 batch norm의 param 전체를 업데이트해야하고
                        generator의 optimizer는 batch_norm param의 generator 부분만 업데이트 해야 한다.   
        '''
        update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS, scope=scope)
        with tf.control_dependencies(update_ops):
            if optimizer_selection == "Adam":
                optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate, beta1=beta1, beta2=beta2)
            elif optimizer_selection == "RMSP":
                optimizer = tf.train.RMSPropOptimizer(learning_rate=learning_rate, decay=decay, momentum=momentum)
            elif optimizer_selection == "SGD":
                optimizer = tf.train.GradientDescentOptimizer(learning_rate=learning_rate)
            train_operation = optimizer.minimize(cost, var_list=var_list)
        return train_operation

    def min_max_loss(logits=None, labels=None):
        return tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=logits, labels=labels))

    # print(tf.get_default_graph()) #기본그래프이다.
    JG_Graph = tf.Graph()  # 내 그래프로 설정한다.- 혹시라도 나중에 여러 그래프를 사용할 경우를 대비
    with JG_Graph.as_default():  # as_default()는 JG_Graph를 기본그래프로 설정한다.

        # 데이터 전처리
        with tf.name_scope("Dataset"):
            dataset = Dataset(DB_name=DB_name, AtoB=AtoB, batch_size=batch_size, use_TFRecord=use_TFRecord,
                              use_TrainDataset=not TEST, training_size=training_size, inference_size=inference_size)
            iterator, next_batch, data_length = dataset.iterator()

            # 알고리즘
            x, target = next_batch

        with tf.name_scope("Origin_image"):
            tf.summary.image("Origin_image", x, max_outputs=3)

        with tf.variable_scope("shared_variables", reuse=tf.AUTO_REUSE) as scope:
            with tf.name_scope("Generator"):
                G = generator(images=x)
                tf.summary.image("generated_image", G, max_outputs=3)
            with tf.name_scope("Discriminator"):
                D_real, sigmoid_D_real = discriminator(images=target, condition=x)
                # scope.reuse_variables()
                D_gene, sigmoid_D_gene = discriminator(images=G, condition=x)

        with tf.name_scope("Generated_image"):
            tf.summary.image("Generated_image", G, max_outputs=3)

        var_D = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES,
                                  scope='shared_variables/Discriminator')

        # set으로 중복 제거 하고, 다시 list로 바꾼다.
        var_G = list(set(np.concatenate(
            (tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='shared_variables/Generator'),
             tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='shared_variables/Generator')),
            axis=0)))

        # Adam optimizer의 매개변수들을 저장하고 싶지 않다면 여기에 선언해야한다.
        with tf.name_scope("saver"):
            saver_all = tf.train.Saver(var_list=tf.global_variables(), max_to_keep=3)
            saver_generator = tf.train.Saver(var_list=var_G, max_to_keep=3)

        if not TEST:

            # Algorithjm - 속이고 속이는 과정

            with tf.name_scope("Discriminator_loss"):
                # for discriminator
                D_Loss = min_max_loss(logits=D_real, labels=tf.ones_like(D_real)) + min_max_loss(logits=D_gene,
                                                                                                 labels=tf.zeros_like(
                                                                                                     D_gene))
            with tf.name_scope("Generator_loss"):
                # for generator
                G_Loss = min_max_loss(logits=D_gene, labels=tf.ones_like(D_gene))

            if distance_loss == "L1":
                with tf.name_scope("{}_loss".format(distance_loss)):
                    dis_loss = tf.losses.absolute_difference(target, G)
                    tf.summary.scalar("{} Loss".format(distance_loss), dis_loss)
                    G_Loss += tf.multiply(dis_loss, distance_loss_weight)
            elif distance_loss == "L2":
                with tf.name_scope("{}_loss".format(distance_loss)):
                    dis_loss = tf.losses.mean_squared_error(target, G)
                    tf.summary.scalar("{} Loss".format(distance_loss), dis_loss)
                    G_Loss += tf.multiply(dis_loss, distance_loss_weight)
            else:
                dis_loss = tf.constant(value=0, dtype=tf.float32)

            with tf.name_scope("Discriminator_trainer"):
                D_train_op = training(D_Loss, var_D, scope=None)
            with tf.name_scope("Generator_trainer"):
                G_train_op = training(G_Loss, var_G, scope='shared_variables/generator')
            with tf.name_scope("tensorboard"):
                summary_operation = tf.summary.merge_all()

    if image_pool and batch_size == 1:
        imagepool = ImagePool(image_pool_size=image_pool_size)

    config = tf.ConfigProto(log_device_placement=False, allow_soft_placement=True)
    config.gpu_options.allow_growth = True
    # config.gpu_options.per_process_gpu_memory_fraction = 0.1

    with tf.Session(graph=JG_Graph, config=config) as sess:
        print("initializing!!!")
        sess.run(tf.global_variables_initializer())
        ckpt_all = tf.train.get_checkpoint_state(os.path.join(model_name, 'All'))
        ckpt_generator = tf.train.get_checkpoint_state(os.path.join(model_name, 'Generator'))
        if (ckpt_all and tf.train.checkpoint_exists(ckpt_all.model_checkpoint_path)) \
                or (ckpt_generator and tf.train.checkpoint_exists(ckpt_generator.model_checkpoint_path)):
            if not TEST:
                print("all variable retored except for optimizer parameter")
                print("Restore {} checkpoint!!!".format(os.path.basename(ckpt_all.model_checkpoint_path)))
                saver_all.restore(sess, ckpt_all.model_checkpoint_path)
            else:
                print("generator variable retored except for optimizer parameter")
                print("Restore {} checkpoint!!!".format(os.path.basename(ckpt_generator.model_checkpoint_path)))
                saver_generator.restore(sess, ckpt_generator.model_checkpoint_path)

        if not TEST:
            summary_writer = tf.summary.FileWriter(os.path.join("tensorboard", model_name), sess.graph)
            sess.run(iterator.initializer)
            for epoch in tqdm(range(1, training_epochs + 1)):
                Loss_D = 0
                Loss_G = 0
                Loss_Distance = 0

                # 아래의 두 변수가 각각 0.5 씩의 값을 갖는게 가장 이상적이다.
                sigmoid_D = 0
                sigmoid_G = 0

                total_batch = int(data_length / batch_size)
                for i in range(total_batch):
                    _, Generator_Loss, Distance_Loss, D_gene_simgoid = sess.run(
                        [G_train_op, G_Loss, dis_loss, sigmoid_D_gene])

                    # image_pool 변수 사용할 때(단 batch_size=1 일 경우만), Discriminator Update
                    if image_pool and batch_size == 1:
                        fake_G = imagepool(image=sess.run(G))
                        # G 에 과거에 생성된 fake_G를 넣어주자!!!
                        _, Discriminator_Loss, D_real_simgoid = sess.run([D_train_op, D_Loss, sigmoid_D_real],
                                                                         feed_dict={G: fake_G})
                    # image_pool 변수를 사용하지 않을 때, Discriminator Update
                    else:
                        _, Discriminator_Loss, D_real_simgoid = sess.run([D_train_op, D_Loss, sigmoid_D_real])

                    Loss_D += (Discriminator_Loss / total_batch)
                    Loss_G += (Generator_Loss / total_batch)
                    Loss_Distance += (Distance_Loss / total_batch)
                    sigmoid_D += D_real_simgoid / total_batch
                    sigmoid_G += D_gene_simgoid / total_batch
                    print("{} epoch : {} batch running of {} total batch...".format(epoch, i, total_batch))

                print("Discriminator mean output : {} / Generator mean output : {}".format(np.mean(sigmoid_D),
                                                                                           np.mean(sigmoid_G)))

                if distance_loss == "L1" or distance_loss == "L2":
                    print(
                        "Discriminator Loss : {} / Generator Loss  : {} / {} loss : {}".format(Loss_D, Loss_G,
                                                                                               distance_loss,
                                                                                               Loss_Distance))
                else:
                    print(
                        "Discriminator Loss : {} / Generator Loss  : {}".format(Loss_D, Loss_G))

                if epoch % display_step == 0:
                    summary_str = sess.run(summary_operation)
                    summary_writer.add_summary(summary_str, global_step=epoch)

                    save_all_model_path = os.path.join(model_name, 'All')
                    save_generator_model_path = os.path.join(model_name, 'Generator')

                    if not os.path.exists(save_all_model_path):
                        os.makedirs(save_all_model_path)
                    if not os.path.exists(save_generator_model_path):
                        os.makedirs(save_generator_model_path)

                    saver_all.save(sess, save_all_model_path + "/", global_step=epoch,
                                   write_meta_graph=False)
                    saver_generator.save(sess, save_generator_model_path + "/", global_step=epoch,
                                         write_meta_graph=False)

            print("Optimization Finished!")

        if TEST:
            sess.run(iterator.initializer)
            for i in range(data_length):
                translated_image, (input, label) = sess.run([G, next_batch])
                visualize(model_name=model_name, named_images=[i, input[0], label[0], translated_image[0]],
                          save_path=save_path)


if __name__ == "__main__":
    # optimizers_ selection = "Adam" or "RMSP" or "SGD"
    model(TEST=False, AtoB=True, DB_name="facades", use_TFRecord=True, distance_loss="L1",
          distance_loss_weight=100, optimizer_selection="Adam",
          beta1=0.5, beta2=0.999,  # for Adam optimizer
          decay=0.999, momentum=0.9,  # for RMSProp optimizer
          # batch_size는 1~10사이로 하자
          image_pool=True,  # discriminator 업데이트시 이전에 generator로 부터 생성된 이미지의 사용 여부
          image_pool_size=50,  # image_pool=True 라면 몇개를 사용 할지?
          learning_rate=0.0002, training_epochs=200, batch_size=1, display_step=1, Dropout_rate=0.5,
          using_moving_variable=False,  # using_moving_variable - 이동 평균, 이동 분산을 사용할지 말지 결정하는 변수
          training_size=(256, 256),  # 학습할 때 입력의 크기
          inference_size=(512, 512),  # 테스트 시 inference 해 볼 크기
          save_path="translated_image")  # 학습 완료 후 변환된 이미지가 저장될 폴더
else:
    print("model imported")
