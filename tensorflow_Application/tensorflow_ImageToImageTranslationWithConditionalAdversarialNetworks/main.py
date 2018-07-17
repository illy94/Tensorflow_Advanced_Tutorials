import ImageToImageTranslation as pix2pix
'''
데이터셋 다운로드는 - https://people.eecs.berkeley.edu/~tinghuiz/projects/pix2pix/datasets/  에서 받았으며,
<edges2shoes 데이터셋> 을 사용여 학습하고 테스트 함. 논문에서 추천하기를 15 epoch, 4 batch size

내가 생각하는 Image-to-Image Translation with cGAN
1. generator 네트워크에 학습, 테스트시 둘다 dropout 적용  
2. discriminator에 patchGAN 적용 - texture/style loss로써 이해될 수 있다고 한다. 
'''
'''
입력크기 : 256x256x3
optimizers_ selection = "Adam" or "RMSP" or "SGD"
batch_size = 1 -> instance norm, batch_size > 1 -> batch_norm
저자코드 따라함 - https://github.com/phillipi/pix2pix/blob/master/models.lua
generator는 unet을 사용한다.
discriminator의 구조는 PatchGAN 70X70을 사용한다. 

distance_loss = 'L1' 일 경우 , generator에서 나오는 출력과 실제 출력값을 비교하는 L1 loss를 생성
distance_loss = 'L2' 일 경우 , generator에서 나오는 출력과 실제 출력값을 비교하는 L2 loss를 생성
distamce_loss = None 일 경우 , 추가적인 loss 없음

patchGAN 은 논문의 저자가 붙인이름이다. - ReceptiveField 에 대한 이해가 필요하다. -> 이 내용에 대해 혼돈이 있을 수 있으니 ref폴더의 안의 receptiveField 내용과 receptiveFieldArithmetic폴더의 receptiveField 크기 구현 코드를 참고한다.
저자의 답변이다.(깃허브의 Issues에서 찾았다.)
This is because the (default) discriminator is a "PatchGAN" (Section 2.2.2 in the paper).
This discriminator slides across the generated image, convolutionally, 
trying to classify if each overlapping 70x70 patch is real or fake. 
This results in a 30x30 grid of classifier outputs, 
each corresponding to a different patch in the generated image.
'''
pix2pix.model(TEST=False, distance_loss="L2", distance_loss_weight=100, optimizer_selection="Adam",
            beta1 = 0.9, beta2 = 0.999, # for Adam optimizer
            decay = 0.999, momentum = 0.9, # for RMSProp optimizer
            #batch_size는 1~10사이로 하자
            learning_rate=0.0002, training_epochs=20, batch_size=4, display_step=1)
